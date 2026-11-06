import { Box, Typography } from '@mui/material';
import { ReactComponent as BrandMark } from '../assets/images/brand/nvis-p2p.svg';
import styles from './brand-panel.module.css';

export default function BrandPanel() {
  return (
    <Box className={styles.panel}>
      <Box className={styles.grid} />
      <Box className={styles.glow} />
      <Box className={styles.content}>
        <Box className={styles.brandRow}>
          <BrandMark className={styles.mark} />
          <Box>
            <Typography className={styles.eyebrow}>NVIS CONTROL PLANE</Typography>
            <Typography component="div" className={styles.wordmark}>
              NVIS-P2P
            </Typography>
          </Box>
        </Box>
        <Typography component="h1" className={styles.headline}>
          Fleet-scale delivery,
          <br />
          <span>without the origin storm.</span>
        </Typography>
        <Typography className={styles.summary}>
          Operate peer-assisted distribution across scheduler clusters, seed peers, and compute nodes from one secure console.
        </Typography>
        <Box className={styles.metrics}>
          <Box className={styles.metric}>
            <Typography className={styles.metricLabel}>PLANE</Typography>
            <Typography className={styles.metricValue}>P2P DATA</Typography>
          </Box>
          <Box className={styles.metric}>
            <Typography className={styles.metricLabel}>POLICY</Typography>
            <Typography className={styles.metricValue}>ORIGIN SAFE</Typography>
          </Box>
          <Box className={styles.metric}>
            <Typography className={styles.metricLabel}>SCOPE</Typography>
            <Typography className={styles.metricValue}>NVIS FLEET</Typography>
          </Box>
        </Box>
      </Box>
      <Typography className={styles.footer}>NVIDIA Infrastructure Services · Peer-to-Peer Distribution</Typography>
    </Box>
  );
}
