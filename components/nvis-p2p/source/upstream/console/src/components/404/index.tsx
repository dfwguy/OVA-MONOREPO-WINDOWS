import { Box, Typography, Grid, Button } from '@mui/material';
import styles from './index.module.css';
import { useNavigate } from 'react-router-dom';
import { ReactComponent as Logo } from '../../assets/images/brand/nvis-p2p.svg';

export default function NotFound() {
  const navigate = useNavigate();

  return (
    <Grid className={styles.container}>
      <Box className={styles.logoContainer}>
        <Logo className={styles.logoIcon} />
        <Typography variant="h6" color="text.primary">
          NVIS-P2P
        </Typography>
      </Box>
      <Box className={styles.content}>
        <Typography
          className={styles.notFound}
          sx={{ color: '#76b900', fontSize: '8rem', fontWeight: 800, lineHeight: 1, letterSpacing: '-0.06em' }}
        >
          404
        </Typography>
        <Typography id="something-went-wrong" variant="h4" gutterBottom mt="2rem" color="#1c293a">
          Something gone wrong!
        </Typography>
        <Typography id="404-help-text" variant="body1" mb="2rem" color="text.secondary">
          The page you were looking for doesn't exist.
        </Typography>
        <Button
          id="go-back"
          variant="contained"
          color="secondary"
          size="large"
          sx={{
            width: '12rem',
            background: '#1c293a',
            color: 'var(--palette-button-text-color)',
            ':hover': { backgroundColor: '#1c293a' },
          }}
          onClick={() => {
            navigate(`/clusters`);
          }}
        >
          <Typography variant="button">go back cluster</Typography>
        </Button>
      </Box>
    </Grid>
  );
}
