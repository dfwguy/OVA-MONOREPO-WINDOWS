import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { CheckCircle, Refresh, Restore, Save, SettingsSuggest } from '@mui/icons-material';

type Settings = {
  peer: {
    download_bandwidth: string;
    upload_bandwidth: string;
    back_to_source_bandwidth: string;
    concurrent_pieces: number;
  };
  scheduler: { redis_pool_size: number; redis_pool_timeout: string };
  service_policy: {
    mode: 'uncapped' | 'explicit';
    cpu_quota_percent: number | null;
    memory_max: string | null;
    nice: number | null;
    io_scheduling_class: string | null;
    io_scheduling_priority: number | null;
  };
};

type Operation = {
  id: string;
  kind: string;
  state: string;
  phase: string;
  started_at: string;
  finished_at?: string;
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  errors: { node: string; return_code: number; detail: string }[];
  log: string;
};

type Status = {
  defaults: Settings;
  desired: Settings;
  drift: string[];
  operations: Operation[];
  active: Operation | null;
  scope: { eligible_nodes: number };
};

type Plan = {
  valid: boolean;
  settings: Settings;
  changed: string[];
  scheduler_reconcile: boolean;
  peer_reconcile: boolean;
  eligible_nodes: number;
  preserves: string[];
};

const api = '/nvis/api/settings';
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const panel = { p: { xs: 2, md: 3 }, bgcolor: '#0c1219', borderColor: '#223242' };

export default function DragonflySettings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async (replaceDraft = false) => {
    try {
      const response = await fetch(api, { credentials: 'include', cache: 'no-store' });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || response.statusText);
      setStatus(body);
      setDraft(current => replaceDraft || !current ? clone(body.desired) : current);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load Dragonfly settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh(true);
    const timer = window.setInterval(() => refresh(false), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const change = (section: keyof Settings, key: string, value: string | number | null) => {
    setDraft(current => current ? { ...current, [section]: { ...current[section], [key]: value } } : current);
    setPlan(null);
    setNotice('');
  };

  const setPolicyMode = (mode: 'uncapped' | 'explicit') => {
    setDraft(current => current ? {
      ...current,
      service_policy: mode === 'uncapped' ? {
        mode,
        cpu_quota_percent: null,
        memory_max: null,
        nice: null,
        io_scheduling_class: null,
        io_scheduling_priority: null,
      } : {
        mode,
        cpu_quota_percent: current.service_policy.cpu_quota_percent ?? 800,
        memory_max: current.service_policy.memory_max ?? '16G',
        nice: current.service_policy.nice ?? 0,
        io_scheduling_class: current.service_policy.io_scheduling_class ?? 'best-effort',
        io_scheduling_priority: current.service_policy.io_scheduling_priority ?? 4,
      },
    } : current);
    setPlan(null);
    setNotice('');
  };

  const request = async (action: 'validate' | 'apply' | 'reconcile') => {
    if (!draft) return;
    if (action === 'apply' && !window.confirm(`Apply these settings and reconcile only affected NVIS-P2P services?\n\nPeer caches, artifacts, and unrelated services are preserved.`)) return;
    if (action === 'reconcile' && !window.confirm(`Reconcile the saved configuration across ${status?.scope.eligible_nodes || 0} eligible nodes?\n\nThis restarts only NVIS-P2P peer/catalog services.`)) return;
    setSubmitting(true);
    setError('');
    try {
      const response = await fetch(`${api}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: draft }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || response.statusText);
      if (action === 'validate') {
        setPlan(body);
        setNotice('Validation passed. Review the dry-run plan before applying.');
      } else {
        setPlan(body.plan || null);
        setNotice(`${action === 'apply' ? 'Apply' : 'Reconcile'} operation ${body.id} started.`);
        await refresh(action === 'apply');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `${action} failed`);
    } finally {
      setSubmitting(false);
    }
  };

  const active = status?.active;
  const progress = active?.total ? (100 * active.completed / active.total) : 0;
  const explicit = draft?.service_policy.mode === 'explicit';
  const dirty = useMemo(() => Boolean(status && draft && JSON.stringify(status.desired) !== JSON.stringify(draft)), [status, draft]);

  if (loading || !draft || !status) return <Box p={4}><CircularProgress /></Box>;

  return (
    <Box sx={{ p: { xs: 1.5, md: 3 }, maxWidth: 1500, mx: 'auto', minHeight: '100%', background: 'radial-gradient(circle at 90% 0%, rgba(118,185,0,.10), transparent 36%)' }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2} mb={3}>
        <Box>
          <Typography variant="overline" color="#76b900">NVIS-P2P CONTROL PLANE</Typography>
          <Typography variant="h4" fontWeight={800}>Dragonfly Settings</Typography>
          <Typography color="text.secondary">Validated, durable fleet policy with atomic configuration updates and scoped reconciliation.</Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          <Chip color={status.drift.length ? 'warning' : 'success'} label={status.drift.length ? `${status.drift.length} file(s) drifted` : 'Runtime templates aligned'} />
          <Button startIcon={<Refresh />} variant="outlined" onClick={() => refresh(true)}>Refresh</Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
      {notice && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
      {active && <Alert severity="info" sx={{ mb: 2 }}>
        <Stack spacing={1}>
          <Typography fontWeight={700}>{active.kind.replaceAll('_', ' ')} · {active.phase.replaceAll('_', ' ')}</Typography>
          <LinearProgress variant={active.total ? 'determinate' : 'indeterminate'} value={progress} sx={{ height: 8, borderRadius: 4 }} />
          <Typography variant="caption">{active.completed}/{active.total} processed · {active.succeeded} succeeded · {active.failed} failed</Typography>
        </Stack>
      </Alert>}

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Stack spacing={2.5}>
            <Paper variant="outlined" sx={panel}>
              <Typography variant="h6" fontWeight={800}>Peer transfer policy</Typography>
              <Typography variant="body2" color="text.secondary" mb={2}>Bandwidth values use Dragonfly units such as 50GB. Direct compute-node access to origin remains disabled.</Typography>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Download bandwidth" value={draft.peer.download_bandwidth} onChange={event => change('peer', 'download_bandwidth', event.target.value)} helperText="Working release: 50GB" /></Grid>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Upload bandwidth" value={draft.peer.upload_bandwidth} onChange={event => change('peer', 'upload_bandwidth', event.target.value)} helperText="Per peer serving capacity" /></Grid>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Back-to-source bandwidth" value={draft.peer.back_to_source_bandwidth} onChange={event => change('peer', 'back_to_source_bandwidth', event.target.value)} helperText="Limit retained for seed/origin roles" /></Grid>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth type="number" label="Concurrent pieces" value={draft.peer.concurrent_pieces} onChange={event => change('peer', 'concurrent_pieces', Number(event.target.value))} inputProps={{ min: 1, max: 256 }} /></Grid>
              </Grid>
            </Paper>

            <Paper variant="outlined" sx={panel}>
              <Typography variant="h6" fontWeight={800}>Scheduler Redis</Typography>
              <Typography variant="body2" color="text.secondary" mb={2}>The working fleet release uses a 1,024-connection pool and 10-second acquisition timeout.</Typography>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth type="number" label="Pool size" value={draft.scheduler.redis_pool_size} onChange={event => change('scheduler', 'redis_pool_size', Number(event.target.value))} inputProps={{ min: 16, max: 8192 }} /></Grid>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Pool timeout" value={draft.scheduler.redis_pool_timeout} onChange={event => change('scheduler', 'redis_pool_timeout', event.target.value)} helperText="Example: 10s" /></Grid>
              </Grid>
            </Paper>

            <Paper variant="outlined" sx={panel}>
              <Typography variant="h6" fontWeight={800}>Peer service resource policy</Typography>
              <Typography variant="body2" color="text.secondary" mb={2}>Uncapped is the validated default: no CPU quota, memory maximum, nice adjustment, or I/O scheduling cap.</Typography>
              <FormControl fullWidth sx={{ mb: 2 }}>
                <InputLabel>Policy</InputLabel>
                <Select label="Policy" value={draft.service_policy.mode} onChange={event => setPolicyMode(event.target.value as 'uncapped' | 'explicit')}>
                  <MenuItem value="uncapped">Uncapped (recommended)</MenuItem>
                  <MenuItem value="explicit">Explicit limits</MenuItem>
                </Select>
              </FormControl>
              {explicit && <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth type="number" label="CPU quota (%)" value={draft.service_policy.cpu_quota_percent ?? ''} onChange={event => change('service_policy', 'cpu_quota_percent', Number(event.target.value))} /></Grid>
                <Grid size={{ xs: 12, sm: 6 }}><TextField fullWidth label="Memory maximum" value={draft.service_policy.memory_max ?? ''} onChange={event => change('service_policy', 'memory_max', event.target.value)} helperText="Example: 8G" /></Grid>
                <Grid size={{ xs: 12, sm: 4 }}><TextField fullWidth type="number" label="Nice" value={draft.service_policy.nice ?? 0} onChange={event => change('service_policy', 'nice', Number(event.target.value))} /></Grid>
                <Grid size={{ xs: 12, sm: 4 }}><FormControl fullWidth><InputLabel>I/O class</InputLabel><Select label="I/O class" value={draft.service_policy.io_scheduling_class ?? 'best-effort'} onChange={event => change('service_policy', 'io_scheduling_class', event.target.value)}><MenuItem value="best-effort">Best effort</MenuItem><MenuItem value="idle">Idle</MenuItem><MenuItem value="realtime">Realtime</MenuItem></Select></FormControl></Grid>
                <Grid size={{ xs: 12, sm: 4 }}><TextField fullWidth type="number" label="I/O priority" value={draft.service_policy.io_scheduling_priority ?? 4} onChange={event => change('service_policy', 'io_scheduling_priority', Number(event.target.value))} inputProps={{ min: 0, max: 7 }} /></Grid>
              </Grid>}
            </Paper>
          </Stack>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack spacing={2.5}>
            <Paper variant="outlined" sx={panel}>
              <Stack direction="row" alignItems="center" spacing={1} mb={1}><SettingsSuggest color="success" /><Typography variant="h6" fontWeight={800}>Safe apply</Typography></Stack>
              <Typography color="text.secondary" variant="body2">Validation renders every affected template before any write. Apply uses atomic replacements, then reconciles only the scheduler and NVIS-P2P peer services that changed.</Typography>
              <Divider sx={{ my: 2 }} />
              <Stack spacing={1.25}>
                <Button variant="outlined" startIcon={<CheckCircle />} disabled={submitting || Boolean(active)} onClick={() => request('validate')}>Validate & dry run</Button>
                <Button variant="contained" startIcon={<Save />} disabled={submitting || Boolean(active) || !dirty || !plan?.valid} onClick={() => request('apply')}>Apply validated settings</Button>
                <Button variant="outlined" color="warning" startIcon={<Refresh />} disabled={submitting || Boolean(active) || dirty} onClick={() => request('reconcile')}>Reconcile saved policy</Button>
                <Button startIcon={<Restore />} disabled={submitting || Boolean(active)} onClick={() => { setDraft(clone(status.defaults)); setPlan(null); }}>Load working defaults</Button>
              </Stack>
              {submitting && <LinearProgress sx={{ mt: 2 }} />}
            </Paper>

            {plan && <Card variant="outlined" sx={{ bgcolor: '#0c1219', borderColor: 'rgba(118,185,0,.55)' }}><CardContent>
              <Typography fontWeight={800} gutterBottom>Dry-run plan</Typography>
              <Stack spacing={1}>
                <Typography variant="body2">Files changing: {plan.changed.length ? plan.changed.join(', ') : 'none'}</Typography>
                <Typography variant="body2">Peer reconcile: {plan.peer_reconcile ? `${plan.eligible_nodes} eligible nodes` : 'not required'}</Typography>
                <Typography variant="body2">Scheduler reconcile: {plan.scheduler_reconcile ? 'scheduler only' : 'not required'}</Typography>
                <Typography variant="caption" color="text.secondary">Preserved: {plan.preserves.join(', ')}.</Typography>
              </Stack>
            </CardContent></Card>}

            <Paper variant="outlined" sx={panel}>
              <Typography variant="h6" fontWeight={800} gutterBottom>Recent settings operations</Typography>
              <Stack spacing={1.25}>
                {status.operations.length === 0 && <Typography color="text.secondary">No settings operations yet.</Typography>}
                {status.operations.map(operation => <Box key={operation.id} sx={{ p: 1.5, border: '1px solid #223242', borderRadius: 1 }}>
                  <Stack direction="row" justifyContent="space-between" gap={1}><Typography fontWeight={700}>{operation.kind.replaceAll('_', ' ')}</Typography><Chip size="small" color={operation.state === 'succeeded' ? 'success' : operation.state === 'failed' || operation.failed ? 'error' : 'info'} label={operation.state.replaceAll('_', ' ')} /></Stack>
                  <Typography variant="caption" color="text.secondary">{operation.started_at} · {operation.completed}/{operation.total} nodes · {operation.failed} failed</Typography>
                  <Box><Button size="small" href={operation.log} target="_blank">Open log</Button></Box>
                </Box>)}
              </Stack>
            </Paper>
          </Stack>
        </Grid>
      </Grid>
    </Box>
  );
}
