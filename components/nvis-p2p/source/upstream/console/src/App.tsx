import Main from './layouts/main';
import { createTheme, ThemeProvider } from '@mui/material';
import { createContext, useEffect, useMemo, useState } from 'react';

export const ColorModeContext = createContext({ toggleColorMode: () => {} });

function App() {
  const [mode, setMode] = useState<'light' | 'dark'>(() => {
    const dataTheme = localStorage.getItem('data-theme');
    return (dataTheme as 'light' | 'dark') || 'dark';
  });

  const colorMode = useMemo(
    () => ({
      toggleColorMode: () => {
        setMode((prevMode) => (prevMode === 'light' ? 'dark' : 'light'));
      },
    }),
    [],
  );

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);

    localStorage.setItem('data-theme', mode);
  }, [mode]);

  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: {
            main: '#76b900',
          },
          text: {
            primary: '#e8f1f8',
            secondary: '#8299aa',
          },
          success: {
            main: '#76b900',
            light: '#9bdd32',
            dark: '#5f9500',
          },
          warning:{
            main:'#ffcb31'
          },
          secondary: {
            main: '#76b900',
            light: '#9bdd32',
            dark: '#5f9500',
          },
          background: {
            default: '#06090d',
            paper: '#111a24',
          },
        },
        typography: {
          fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
        components: {
          MuiDialog: {
            styleOverrides: {
              paper: {
                backgroundColor: 'var(--palette-profile-background-paper)',
                backgroundImage: 'none',
              },
            },
          },
          MuiAlert: {
            defaultProps: {
              variant: 'filled',
            },
          },
        },
      }),
    [mode],
  );

  return (
    <ColorModeContext.Provider value={colorMode}>
      <ThemeProvider theme={theme}>
        <Main />
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}

export default App;
