// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: LicenseRef-NvidiaProprietary
//! WebSocket transport for the interactive terminal (`/ws/terminal`).
//!
//! The terminal is the one place the CLI needs a socket rather than a request/response, so this is
//! the only WebSocket in the crate. It reuses the same [`TlsTrust`](crate::TlsTrust) policy the HTTP
//! client honours — system roots, a pinned CA, or (explicitly) skip verification — built on rustls
//! with the aws-lc-rs provider, the same stack reqwest uses, so the binary carries one TLS
//! implementation and no system OpenSSL dependency.
//!
//! Auth rides on the handshake: the access token goes in `Authorization: Bearer`, exactly as an HTTP
//! call. The server's `/ws/terminal` gate explicitly allows a client that sends **no** `Origin`
//! header (it is how it tells a browser from a script), so the CLI sends none and is accepted.

use std::sync::Arc;

use rustls::pki_types::pem::PemObject;
use rustls::pki_types::CertificateDer;
use tokio::net::TcpStream;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::StatusCode;
use tokio_tungstenite::{
    connect_async_tls_with_config, Connector, MaybeTlsStream, WebSocketStream,
};
use url::Url;

use crate::{Error, Result, TlsTrust};

/// Re-exported so the binary can name the frame type and the closed-connection error without a
/// direct dependency on a specific tungstenite version.
pub use tokio_tungstenite::tungstenite::Message;

/// The connected terminal socket. Split it into a sink/stream to pump bytes both ways.
pub type WsStream = WebSocketStream<MaybeTlsStream<TcpStream>>;

/// Build the `ws://`/`wss://` URL for a terminal session from the HTTP base URL and query params.
/// `wss` when the base is `https`, `ws` otherwise, preserving host and port.
pub fn terminal_url(base_url: &Url, query: &[(&str, &str)]) -> Result<Url> {
    let mut url = base_url.join("/ws/terminal").map_err(Error::Url)?;
    let scheme = if base_url.scheme() == "https" {
        "wss"
    } else {
        "ws"
    };
    url.set_scheme(scheme)
        .map_err(|_| Error::WebSocket(format!("cannot set {scheme} scheme")))?;
    {
        let mut qp = url.query_pairs_mut();
        for (k, v) in query {
            qp.append_pair(k, v);
        }
    }
    Ok(url)
}

/// Open a terminal WebSocket to `base_url` with the given TLS trust and bearer token. A 401 during
/// the handshake surfaces as [`Error::Unauthorized`], so the caller can refresh and retry exactly as
/// it does for an HTTP 401.
pub async fn connect_terminal(
    base_url: &Url,
    tls: &TlsTrust,
    query: &[(&str, &str)],
    bearer: Option<&str>,
) -> Result<WsStream> {
    let url = terminal_url(base_url, query)?;
    let mut request = url
        .as_str()
        .into_client_request()
        .map_err(|e| Error::WebSocket(e.to_string()))?;
    if let Some(token) = bearer {
        let value = format!("Bearer {token}")
            .parse()
            .map_err(|_| Error::WebSocket("invalid bearer token".into()))?;
        request.headers_mut().insert(
            tokio_tungstenite::tungstenite::http::header::AUTHORIZATION,
            value,
        );
    }

    let connector = if base_url.scheme() == "https" {
        Some(Connector::Rustls(rustls_config(tls)?))
    } else {
        None
    };

    match connect_async_tls_with_config(request, None, false, connector).await {
        Ok((stream, _resp)) => Ok(stream),
        Err(tokio_tungstenite::tungstenite::Error::Http(resp))
            if resp.status() == StatusCode::UNAUTHORIZED =>
        {
            Err(Error::Unauthorized { message: None })
        }
        Err(e) => Err(Error::WebSocket(e.to_string())),
    }
}

/// Build a rustls client config for the given trust policy.
fn rustls_config(tls: &TlsTrust) -> Result<Arc<rustls::ClientConfig>> {
    let provider = Arc::new(rustls::crypto::aws_lc_rs::default_provider());

    let builder = rustls::ClientConfig::builder_with_provider(provider.clone())
        .with_safe_default_protocol_versions()
        .map_err(|e| Error::Tls(e.to_string()))?;

    let config = match tls {
        TlsTrust::Insecure => builder
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(danger::NoVerification(provider)))
            .with_no_client_auth(),
        TlsTrust::SystemRoots | TlsTrust::AddRootPem(_) => {
            let mut roots = rustls::RootCertStore::empty();
            for cert in rustls_native_certs::load_native_certs().certs {
                let _ = roots.add(cert);
            }
            if let TlsTrust::AddRootPem(pem) = tls {
                // pki-types' own PEM reader, which superseded the unmaintained rustls-pemfile
                // (RUSTSEC-2025-0134).
                for cert in CertificateDer::pem_slice_iter(pem) {
                    let cert = cert.map_err(|e| Error::Tls(format!("pinned cert: {e}")))?;
                    roots
                        .add(cert)
                        .map_err(|e| Error::Tls(format!("pinned cert: {e}")))?;
                }
            }
            builder.with_root_certificates(roots).with_no_client_auth()
        }
    };
    Ok(Arc::new(config))
}

/// The certificate verifier for `TlsTrust::Insecure`. It accepts any certificate, which is what
/// `--insecure` means: use it only for first contact with a self-signed box whose cert has not yet
/// been pinned. Signature checks still run so the handshake itself remains well-formed.
mod danger {
    use std::sync::Arc;

    use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
    use rustls::crypto::{verify_tls12_signature, verify_tls13_signature, CryptoProvider};
    use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
    use rustls::{DigitallySignedStruct, Error, SignatureScheme};

    #[derive(Debug)]
    pub struct NoVerification(pub Arc<CryptoProvider>);

    impl ServerCertVerifier for NoVerification {
        fn verify_server_cert(
            &self,
            _end_entity: &CertificateDer<'_>,
            _intermediates: &[CertificateDer<'_>],
            _server_name: &ServerName<'_>,
            _ocsp_response: &[u8],
            _now: UnixTime,
        ) -> Result<ServerCertVerified, Error> {
            Ok(ServerCertVerified::assertion())
        }

        fn verify_tls12_signature(
            &self,
            message: &[u8],
            cert: &CertificateDer<'_>,
            dss: &DigitallySignedStruct,
        ) -> Result<HandshakeSignatureValid, Error> {
            verify_tls12_signature(
                message,
                cert,
                dss,
                &self.0.signature_verification_algorithms,
            )
        }

        fn verify_tls13_signature(
            &self,
            message: &[u8],
            cert: &CertificateDer<'_>,
            dss: &DigitallySignedStruct,
        ) -> Result<HandshakeSignatureValid, Error> {
            verify_tls13_signature(
                message,
                cert,
                dss,
                &self.0.signature_verification_algorithms,
            )
        }

        fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
            self.0.signature_verification_algorithms.supported_schemes()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_base_becomes_wss_and_keeps_hostport() {
        let base = Url::parse("https://localhost:5000").unwrap();
        let url = terminal_url(&base, &[("mode", "node"), ("target", "n04")]).unwrap();
        assert_eq!(url.scheme(), "wss");
        assert_eq!(url.host_str(), Some("localhost"));
        assert_eq!(url.port(), Some(5000));
        assert_eq!(url.path(), "/ws/terminal");
        let q = url.query().unwrap();
        assert!(q.contains("mode=node"));
        assert!(q.contains("target=n04"));
    }

    #[test]
    fn http_base_becomes_ws() {
        let base = Url::parse("http://127.0.0.1:8080").unwrap();
        let url = terminal_url(&base, &[]).unwrap();
        assert_eq!(url.scheme(), "ws");
    }

    /// A self-signed P-256 root, valid until 2126, generated for these tests only.
    const PINNED_ROOT: &str = "-----BEGIN CERTIFICATE-----
MIIBiDCCAS+gAwIBAgIUKTjZWCkBIJ4cwuGwUOuxvxkGXbAwCgYIKoZIzj0EAwIw
GTEXMBUGA1UEAwwObnZycy10ZXN0LXJvb3QwIBcNMjYxMDI1MTQwMzI2WhgPMjEy
NjEwMDExNDAzMjZaMBkxFzAVBgNVBAMMDm52cnMtdGVzdC1yb290MFkwEwYHKoZI
zj0CAQYIKoZIzj0DAQcDQgAELnVuVLQUp+9PDq6G5OKihD87YiOMZviwQBgaYAPX
ZJX/8ERlyZpAfICJ2hiRhUHrD8gQOkRbpbxzHMZhji98LaNTMFEwHQYDVR0OBBYE
FA8NkPct6MM4MBf0pZcFQ/OPUBmSMB8GA1UdIwQYMBaAFA8NkPct6MM4MBf0pZcF
Q/OPUBmSMA8GA1UdEwEB/wQFMAMBAf8wCgYIKoZIzj0EAwIDRwAwRAIgApgWrVQl
uJDuVm4C0x57pY6Y7JzwRDVcnJZxJU/BzWUCIFitmfEWBX7clc8u7W4m8LgQhrYv
ApJGB5dGBOFf63yv
-----END CERTIFICATE-----
";

    #[test]
    fn a_pinned_root_pem_is_trusted() {
        let tls = TlsTrust::AddRootPem(PINNED_ROOT.as_bytes().to_vec());
        assert!(rustls_config(&tls).is_ok());
    }

    #[test]
    fn a_corrupt_pinned_pem_is_refused_not_skipped() {
        // A pin that silently parses to nothing would leave only the system roots, so a typo in
        // the pinned file must surface as an error rather than as an unexpected trust decision.
        let corrupt = PINNED_ROOT.replacen("MIIB", "M!IB", 1);
        let tls = TlsTrust::AddRootPem(corrupt.into_bytes());
        let err = rustls_config(&tls).unwrap_err().to_string();
        assert!(err.contains("pinned cert"), "{err}");
    }
}
