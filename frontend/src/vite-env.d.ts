/// <reference types="vite/client" />

declare module "*?url" {
  const src: string;
  export default src;
}

// Browser-side .docx import (FileBrowser): mammoth + turndown ship no
// types and there are no @types/* packages for the versions we use.
// The local FileBrowser.importDocx caller treats both APIs as
// loose `unknown` shapes anyway.
declare module "mammoth/mammoth.browser.js";
declare module "turndown";
