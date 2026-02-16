declare module 'react-dom/client' {
  import type { ReactElement } from 'react';
  export function createRoot(container: Element | null): {
    render(element: ReactElement | string | number | null): void;
  };
}
declare module 'react-dom/client' {
  export * from 'react-dom';
}
