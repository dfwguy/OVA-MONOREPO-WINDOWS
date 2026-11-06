import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import { CheckCircle, CloudSync, PlayArrow, Refresh, Storage, VerifiedUser } from '@mui/icons-material';

type ImageRecord = {
  order: number;
  name: string;
  filename: string;
  bytes: number;
  sha256: string;
  canonical_present: boolean;
  persistent_import: string[] | null;
  required_by?: string[];
};

type FleetRecord = {
  su: number;
  total: number;
  reachable: number;
  eligible: number;
  peers: number;
  ready: number;
  syncing: number;
  incomplete: number;
  unavailable: number;
  distribution: Record<string, number>;
};

type NodeCoverage = {
  node: string;
  su: number;
  state: string;
  present: number;
  verified: number;
  unverified: number;
  missing: number;
  bad_size: number;
  active: number;
  images: Record<string, string>;
  observed_at: string | null;
  sync_state?: string;
  sync_detail?: string;
};

type Coverage = {
  generated_at: string | null;
  required_count: number;
  required_images: string[];
  nodes: NodeCoverage[];
};

type Operation = {
  id: string;
  action: string;
  state: string;
  started_at: string;
  finished_at?: string;
  sus: number[];
  images: string[];
  log: string;
};

type Status = {
  catalog: { canonical_directory: string; images: ImageRecord[] };
  object_store_healthy: boolean;
  fleet: FleetRecord[];
  preflight_generated_at: string | null;
  operations: Operation[];
  coverage: Coverage;
  catalog_exact_duplicates: string[][];
  sync: { id: string; state: string; total: number; complete: number; pending: number; deferred: number; percent: number; updated_at: string } | null;
};

const api = '/nvis/api';

export default function ArtifactFleet() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [selectedSus, setSelectedSus] = useState<number[]>(Array.from({ length: 14 }, (_, index) => index + 1));
  const [selectedImages, setSelectedImages] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${api}/status`, { credentials: 'include', cache: 'no-store' });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || response.statusText);
      setStatus(body);
      setSelectedImages(current => current.length ? current : body.catalog.images.map((image: ImageRecord) => image.filename));
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load NVIS artifact status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const active = useMemo(() => status?.operations.some(operation => operation.state === 'running') || false, [status]);
  const totals = useMemo(() => (status?.fleet || []).reduce((sum, item) => ({
    total: sum.total + item.total,
    reachable: sum.reachable + item.reachable,
    eligible: sum.eligible + item.eligible,
    peers: sum.peers + item.peers,
    ready: sum.ready + item.ready,
    syncing: sum.syncing + item.syncing,
  }), { total: 0, reachable: 0, eligible: 0, peers: 0, ready: 0, syncing: 0 }), [status]);

  const nodeCategory = useCallback((node: NodeCoverage) => {
    if (['not-eligible', 'unreachable', 'unavailable'].includes(node.state)) return 'unavailable';
    if (node.active || node.state === 'syncing') return 'syncing';
    if (node.state === 'complete' && node.verified === (status?.coverage.required_count || 0)) return 'complete';
    return 'incomplete';
  }, [status?.coverage.required_count]);

  const categoryColor: Record<string, string> = {
    complete: '#76b900',
    syncing: '#22a7f0',
    incomplete: '#f2a900',
    unavailable: '#536273',
  };

  const coverageCounts = useMemo(() => (status?.coverage.nodes || []).reduce((counts, node) => {
    const category = nodeCategory(node);
    counts[category] += 1;
    return counts;
  }, { complete: 0, syncing: 0, incomplete: 0, unavailable: 0 } as Record<string, number>), [status?.coverage.nodes, nodeCategory]);

  const panelSx = { p: { xs: 1.5, md: 2 }, mb: 3, bgcolor: '#0c1219', borderColor: '#223242' };

  const run = async (action: string) => {
    if (!selectedSus.length) return setError('Select at least one SU.');
    if (['persist', 'distribute', 'repair'].includes(action) && !selectedImages.length) return setError('Select at least one image.');
    if (['distribute', 'repair'].includes(action) && selectedImages.length !== 1) return setError('Distribute or repair one image at a time to keep fleet load bounded.');
    const operationImages = ['persist', 'distribute', 'repair'].includes(action) ? selectedImages : [];
    const description = `${action.toUpperCase()} on ${selectedSus.length} SU(s)` + (operationImages.length ? ` for ${operationImages.length} image(s)` : '');
    if (!window.confirm(`${description}?\n\nThe controller will use the preflight allow-list and will not touch excluded nodes.`)) return;
    try {
      const response = await fetch(`${api}/operations`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, sus: selectedSus, images: operationImages }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || response.statusText);
      setError('');
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Operation failed to start');
    }
  };

  const toggleSu = (su: number) => setSelectedSus(value => value.includes(su) ? value.filter(item => item !== su) : [...value, su].sort((a, b) => a - b));
  const toggleImage = (filename: string) => setSelectedImages(value => value.includes(filename) ? value.filter(item => item !== filename) : [...value, filename]);

  if (loading) return <Box p={4}><CircularProgress /></Box>;

  return (
    <Box sx={{ p: { xs: 1.5, md: 3 }, maxWidth: 1880, mx: 'auto', minHeight: '100%', background: 'radial-gradient(circle at 85% 0%, rgba(118,185,0,.08), transparent 32%)' }}>
      <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2} mb={3}>
        <Box>
          <Typography variant="overline" color="#76b900">NVIS CONTROL PLANE</Typography>
          <Typography variant="h4" fontFamily="mabry-bold">Artifact Fleet</Typography>
          <Typography color="text.secondary">Persistent Dragonfly storage and verified delivery for the complete validation-image catalog.</Typography>
        </Box>
        <Button startIcon={<Refresh />} variant="outlined" onClick={refresh}>Refresh</Button>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
      {active && <Alert severity="info" sx={{ mb: 2 }}>A fleet operation is running. Mutating controls remain locked until it finishes.</Alert>}

      {status?.sync && <Paper variant="outlined" sx={{ ...panelSx, borderColor: status.sync.deferred ? '#f2a900' : 'rgba(118,185,0,.55)' }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" gap={1} mb={1}>
          <Box><Typography fontWeight={800}>Latest catalog sync wave</Typography><Typography variant="caption" color="text.secondary">{status.sync.id} · updated {status.sync.updated_at}</Typography></Box>
          <Chip size="small" color={status.sync.state === 'running' ? 'info' : status.sync.deferred ? 'warning' : 'success'} label={status.sync.state.replaceAll('_', ' ')} />
        </Stack>
        <LinearProgress variant="determinate" value={status.sync.percent} sx={{ height: 8, borderRadius: 4, mb: 1, '& .MuiLinearProgress-bar': { bgcolor: '#76b900' } }} />
        <Typography variant="body2">{status.sync.complete.toLocaleString()} complete · {status.sync.pending.toLocaleString()} pending · {status.sync.deferred.toLocaleString()} deferred · {status.sync.percent}%</Typography>
      </Paper>}

      <Grid container spacing={2} mb={3}>
        {[
          ['Catalog images', `${status?.coverage.required_count || 0}`, (status?.coverage.required_count || 0) === (status?.catalog.images.length || 0)],
          ['Object store', status?.object_store_healthy ? 'Healthy' : 'Unavailable', status?.object_store_healthy],
          ['Reachable nodes', `${totals.reachable} / ${totals.total}`, totals.reachable === totals.total],
          ['Eligible nodes', `${totals.eligible}`, totals.eligible === totals.reachable],
          ['Persistent peers', `${totals.peers}`, totals.peers === totals.eligible],
          ['Verified complete', `${totals.ready}`, totals.ready === totals.eligible],
        ].map(([label, value, good]) => (
          <Grid size={{ xs: 12, sm: 6, lg: 2 }} key={String(label)}>
            <Card variant="outlined" sx={{ height: '100%', bgcolor: '#0c1219', borderColor: good ? 'rgba(118,185,0,.65)' : '#223242' }}>
              <CardContent>
                <Typography color="text.secondary" variant="body2">{String(label)}</Typography>
                <Typography variant="h5" fontFamily="mabry-bold">{String(value)}</Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Paper variant="outlined" sx={panelSx}>
        <Typography variant="h6" gutterBottom>1. Select service units</Typography>
        <Stack direction="row" flexWrap="wrap" gap={0.5}>
          {(status?.fleet || []).map(item => (
            <FormControlLabel key={item.su} control={<Checkbox checked={selectedSus.includes(item.su)} onChange={() => toggleSu(item.su)} />} label={`SU${item.su}`} />
          ))}
        </Stack>
        <Stack direction="row" spacing={1}>
          <Button size="small" onClick={() => setSelectedSus(Array.from({ length: 14 }, (_, i) => i + 1))}>All</Button>
          <Button size="small" onClick={() => setSelectedSus([])}>None</Button>
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={panelSx}>
        <Typography variant="h6" gutterBottom>2. Select canonical images</Typography>
        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 1050 }}>
            <TableHead><TableRow><TableCell /><TableCell>Image</TableCell><TableCell>Required by</TableCell><TableCell>Canonical file</TableCell><TableCell>Size</TableCell><TableCell>SHA-256</TableCell><TableCell>dfstore</TableCell></TableRow></TableHead>
            <TableBody>
              {(status?.catalog.images || []).map(image => (
                <TableRow key={image.filename} hover>
                  <TableCell><Checkbox checked={selectedImages.includes(image.filename)} onChange={() => toggleImage(image.filename)} /></TableCell>
                  <TableCell><Typography fontWeight={700}>{image.order}. {image.name}</Typography></TableCell>
                  <TableCell>{(image.required_by || []).join(' · ')}</TableCell>
                  <TableCell>{image.filename}</TableCell>
                  <TableCell>{(image.bytes / 1e9).toFixed(2)} GB</TableCell>
                  <TableCell><Typography fontFamily="monospace" fontSize={12}>{image.sha256.slice(0, 16)}…</Typography></TableCell>
                  <TableCell><Chip size="small" color={image.persistent_import ? 'success' : 'default'} label={image.persistent_import ? 'Imported' : 'Not imported'} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <Typography variant="caption" color="text.secondary">
          Exact content duplicates in the required catalog: {status?.catalog_exact_duplicates.length || 0}. Same-size files with different SHA-256 values are not duplicates.
        </Typography>
      </Paper>

      <Paper variant="outlined" sx={panelSx}>
        <Typography variant="h6" gutterBottom>3. Run the workflow in order</Typography>
        <Typography color="text.secondary" mb={2}>Each action is allow-list driven. Sync catalog starts the native dfstore service for the complete catalog on the selected SUs and waits for an explicit successful completion from every available node.</Typography>
        <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1}>
          <Button disabled={active} variant="outlined" startIcon={<VerifiedUser />} onClick={() => run('preflight')}>A. Preflight</Button>
          <Button disabled={active} variant="outlined" startIcon={<PlayArrow />} onClick={() => run('deploy')}>B. Install peers</Button>
          <Button disabled={active} variant="outlined" startIcon={<Storage />} onClick={() => run('persist')}>C. Persist selected</Button>
          <Button disabled={active} variant="contained" startIcon={<CloudSync />} onClick={() => run('sync')}>D. Sync catalog</Button>
          <Button disabled={active} variant="outlined" startIcon={<CheckCircle />} onClick={() => run('verify')}>E. Verify fleet</Button>
          <Button disabled={active} variant="outlined" onClick={() => run('distribute')}>Legacy single-image rollout</Button>
          <Button disabled={active} color="warning" variant="outlined" onClick={() => run('repair')}>Repair selected image</Button>
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={panelSx}>
        <Typography variant="h6" gutterBottom>SU readiness</Typography>
        <Typography variant="caption" color="text.secondary">Preflight snapshot: {status?.preflight_generated_at || 'not run'}</Typography>
        <TableContainer>
          <Table size="small">
            <TableHead><TableRow><TableCell>SU</TableCell><TableCell>Reachable</TableCell><TableCell>Eligible</TableCell><TableCell>Peers</TableCell>{Array.from({ length: (status?.coverage.required_count || 0) + 1 }, (_, count) => <TableCell key={count}>{count} images</TableCell>)}<TableCell>Complete</TableCell><TableCell>Syncing</TableCell><TableCell>Incomplete</TableCell><TableCell>Unavailable</TableCell><TableCell>Peer coverage</TableCell></TableRow></TableHead>
            <TableBody>{(status?.fleet || []).map(item => <TableRow key={item.su}>
              <TableCell sx={{ fontWeight: 700, color: '#9bdd32' }}>SU{item.su}</TableCell><TableCell>{item.reachable}/{item.total}</TableCell><TableCell>{item.eligible}</TableCell><TableCell>{item.peers}</TableCell>{Array.from({ length: (status?.coverage.required_count || 0) + 1 }, (_, count) => <TableCell key={count}>{item.distribution?.[String(count)] || 0}</TableCell>)}<TableCell>{item.ready}</TableCell><TableCell>{item.syncing}</TableCell><TableCell>{item.incomplete}</TableCell><TableCell>{item.unavailable}</TableCell>
              <TableCell sx={{ minWidth: 180 }}><LinearProgress variant="determinate" value={item.eligible ? 100 * item.peers / item.eligible : 0} /></TableCell>
            </TableRow>)}</TableBody>
          </Table>
        </TableContainer>
      </Paper>

      <Paper variant="outlined" sx={panelSx}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" gap={1}>
          <Box>
            <Typography variant="h6">4032-node catalog heatmap</Typography>
            <Typography variant="caption" color="text.secondary">Latest observations through {status?.coverage.generated_at || 'not run'} · 24 racks × 12 nodes in each SU · showing {(status?.coverage.nodes || []).filter(node => selectedSus.includes(node.su)).length.toLocaleString()} nodes.</Typography>
          </Box>
          <Stack direction="row" flexWrap="wrap" gap={1} aria-label="Heatmap legend">
            {(['complete', 'syncing', 'incomplete', 'unavailable'] as const).map(category => <Chip key={category} size="small" icon={<Box component="span" sx={{ width: 9, height: 9, borderRadius: '2px', bgcolor: categoryColor[category] }} />} label={`${category[0].toUpperCase()}${category.slice(1)} ${coverageCounts[category]}`} />)}
          </Stack>
        </Stack>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 286px), 1fr))', gap: 1.25, mt: 2 }}>
          {(status?.fleet || []).filter(item => selectedSus.includes(item.su)).map(item => (
            <Box key={item.su} sx={{ minWidth: 0, p: 1.25, bgcolor: '#080d12', border: '1px solid #223242', borderRadius: 1.5 }}>
              <Stack direction="row" justifyContent="space-between" mb={0.75}><Typography fontWeight={800} color="#9bdd32">SU{item.su}</Typography><Typography variant="caption" color="text.secondary">{item.ready}/{item.total} complete</Typography></Stack>
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(24, minmax(7px, 1fr))', gap: '2px', maxWidth: 336 }}>
                {(status?.coverage.nodes || []).filter(node => node.su === item.su).map(node => {
                  const byState = (state: string) => Object.entries(node.images).filter(([, value]) => value === state).map(([filename]) => filename);
                  const missing = [...byState('missing'), ...byState('bad-size')];
                  const unverified = byState('present-unverified');
                  const detail = `${node.node}\n${nodeCategory(node).toUpperCase()} · ${node.present}/${status?.coverage.required_count} present · ${node.verified} verified${node.active ? ' · sync active' : ''}${node.sync_state ? `\nWave: ${node.sync_state}${node.sync_detail ? ` — ${node.sync_detail}` : ''}` : ''}${missing.length ? `\nMissing/bad: ${missing.join(', ')}` : ''}${unverified.length ? `\nPresent, unverified: ${unverified.join(', ')}` : ''}${!Object.keys(node.images).length && node.missing ? '\nImage-level detail unavailable in this snapshot; run Verify fleet.' : ''}${node.observed_at ? `\nVerified: ${node.observed_at}` : '\nNo verification observation'}`;
                  return <Tooltip key={node.node} title={<span style={{ whiteSpace: 'pre-line' }}>{detail}</span>} arrow enterTouchDelay={0}><Box component="span" tabIndex={0} aria-label={detail.replaceAll('\n', '. ')} sx={{ display: 'block', aspectRatio: '1', minWidth: 7, maxWidth: 12, bgcolor: categoryColor[nodeCategory(node)], borderRadius: '2px', outline: node.bad_size ? '1px solid #ff5b5b' : '1px solid rgba(255,255,255,.05)', cursor: 'help', '&:focus-visible': { outline: '2px solid #e8f1f8', zIndex: 1 } }} /></Tooltip>;
                })}
              </Box>
            </Box>
          ))}
        </Box>
      </Paper>

      <Paper variant="outlined" sx={{ ...panelSx, mb: 0 }}>
        <Typography variant="h6" gutterBottom>Recent operations</Typography>
        <TableContainer><Table size="small"><TableHead><TableRow><TableCell>Started</TableCell><TableCell>Action</TableCell><TableCell>Scope</TableCell><TableCell>State</TableCell><TableCell>Log</TableCell></TableRow></TableHead>
          <TableBody>{(status?.operations || []).map(operation => <TableRow key={operation.id}>
            <TableCell>{operation.started_at}</TableCell><TableCell>{operation.action}</TableCell><TableCell>{operation.sus.length} SU / {operation.images.length} image</TableCell>
            <TableCell><Chip size="small" color={operation.state === 'succeeded' ? 'success' : operation.state === 'failed' ? 'error' : 'info'} label={operation.state} /></TableCell>
            <TableCell><Button size="small" href={operation.log} target="_blank">Open log</Button></TableCell>
          </TableRow>)}</TableBody>
        </Table></TableContainer>
      </Paper>
    </Box>
  );
}
