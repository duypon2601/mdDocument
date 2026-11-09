const FRONT_MATTER = /^---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/

/** Bỏ khối front-matter YAML ở đầu file (--- ... ---) nếu có. */
export function stripFrontMatter(md: string): string {
  const body = md.charCodeAt(0) === 0xfeff ? md.slice(1) : md
  const m = FRONT_MATTER.exec(body)
  return m ? body.slice(m[0].length).replace(/^\s*\n/, '') : body
}
