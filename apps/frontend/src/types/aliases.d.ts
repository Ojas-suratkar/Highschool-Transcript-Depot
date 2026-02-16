// Allow imports using the `@/` Vite alias in editor/TS server
declare module '@/*' {
  const anyExport: any;
  export default anyExport;
}
