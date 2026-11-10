import { http, HttpResponse } from 'msw'
import { STATUSES, type Document, type QueuePart, type QueueSnapshot, type Stats } from '../api/types'

/** Dữ liệu mẫu đúng hợp đồng API. Test có thể ghi đè bằng server.use(...). */
export const sampleDocs: Document[] = [
  doc('a'.repeat(64), 'bao-cao-tai-chinh.xlsx', 'INDEXED', { chunk_count: 12 }),
  doc('b'.repeat(64), 'hop-dong-scan.pdf', 'CONVERTING'),
  doc('c'.repeat(64), 'bien-ban-họp.docx', 'NEEDS_REVIEW'),
  doc('d'.repeat(64), 'loi.pdf', 'FAILED', { error_code: 'OCR_FAILED' }),
]

export function doc(
  doc_id: string,
  file_name: string,
  status: Document['status'],
  extra: Partial<Document> = {},
): Document {
  return {
    doc_id,
    file_name,
    mime: 'application/pdf',
    size: 123456,
    status,
    error_code: null,
    chunk_count: 0,
    index_version: 1,
    embedding_model: 'bge-m3',
    created_at: '2026-11-09T05:00:00',
    updated_at: '2026-11-09T05:01:00',
    extract_media: true,
    profile: 'v2',
    ...extra,
  }
}

export function sampleStats(): Stats {
  const by_status = Object.fromEntries(STATUSES.map((s) => [s, 0])) as Stats['by_status']
  for (const d of sampleDocs) by_status[d.status]++
  return { total: sampleDocs.length, chunks: 12, by_status }
}

const part = (identities: string[], backlog = 0): QueuePart => ({
  pollers: identities.map((identity) => ({ identity, last_access: '2026-11-10T03:00:00Z' })),
  backlog,
  backlog_age_s: backlog ? 42 : 0,
  add_rate: 0,
  dispatch_rate: 0,
})

/** Mẫu: convert-tq không có worker và có 3 task chờ; một workflow đang chờ OCR. */
export function sampleQueues(): QueueSnapshot {
  return {
    fetched_at: '2026-11-10T03:00:05Z',
    queues: [
      { name: 'ingest-tq', expects_workflow: true, workflow: part(['8@index']), activity: part(['8@index']) },
      { name: 'convert-tq', expects_workflow: false, workflow: part([]), activity: part([], 3) },
      { name: 'index-tq', expects_workflow: false, workflow: part([]), activity: part(['8@index']) },
    ],
    running: [
      {
        workflow_id: `ingest-${sampleDocs[1].doc_id}`,
        workflow_type: 'DocumentIngestionWorkflow',
        doc_id: sampleDocs[1].doc_id,
        file_name: sampleDocs[1].file_name,
        status: 'CONVERTING',
        started_at: '2026-11-10T02:58:05Z',
        activities: [
          {
            name: 'ocr_pages',
            task_queue: 'convert-tq',
            state: 'SCHEDULED',
            attempt: 2,
            scheduled_at: '2026-11-10T02:59:05Z',
            started_at: null,
            worker: null,
            last_failure: 'timeout',
          },
        ],
      },
    ],
    running_truncated: false,
  }
}

const notFound = () => HttpResponse.json({ detail: 'Không tìm thấy tài liệu' }, { status: 404 })

export const handlers = [
  http.get('/documents', ({ request }) => {
    const url = new URL(request.url)
    const wanted = url.searchParams.get('status')?.split(',')
    const q = url.searchParams.get('q')?.toLowerCase()
    const limit = Number(url.searchParams.get('limit') ?? 20)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    let items = sampleDocs
    if (wanted) items = items.filter((d) => wanted.includes(d.status))
    if (q) items = items.filter((d) => d.file_name.toLowerCase().includes(q))
    return HttpResponse.json({
      items: items.slice(offset, offset + limit),
      total: items.length,
      limit,
      offset,
    })
  }),

  http.post('/documents', async ({ request }) => {
    const form = await request.formData()
    const file = form.get('file') as File
    const created = doc('e'.repeat(64), file.name, 'RECEIVED', { size: file.size })
    return HttpResponse.json({ duplicate: false, ...created }, { status: 202 })
  }),

  http.post('/documents/batch', () => HttpResponse.json({ results: [] })),

  // Khai báo trước /documents/:id/... để không bị khớp nhầm
  http.post('/documents/cancel-running', () =>
    HttpResponse.json(
      { requested: sampleDocs.filter((d) => d.status === 'CONVERTING').map((d) => d.doc_id), failed: [] },
      { status: 202 },
    ),
  ),

  http.get('/documents/:id', ({ params }) => {
    const d = sampleDocs.find((x) => x.doc_id === params.id)
    return d ? HttpResponse.json({ ...d, progress: d.status === 'CONVERTING' ? 'CONVERTING' : null }) : notFound()
  }),

  http.get('/documents/:id/markdown', ({ params }) => {
    const d = sampleDocs.find((x) => x.doc_id === params.id)
    if (!d) return notFound()
    return new HttpResponse('# Tiêu đề\n\n| a | b |\n|---|---|\n| 1 | 2 |\n', {
      headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
    })
  }),

  http.get('/documents/:id/raw', ({ params }) => {
    const d = sampleDocs.find((x) => x.doc_id === params.id)
    if (!d) return notFound()
    return new HttpResponse('%PDF-1.4', {
      headers: {
        'Content-Type': d.mime,
        'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(d.file_name)}`,
      },
    })
  }),

  http.get('/documents/:id/chunks', ({ params, request }) => {
    const d = sampleDocs.find((x) => x.doc_id === params.id)
    if (!d) return notFound()
    const url = new URL(request.url)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const limit = Number(url.searchParams.get('limit') ?? 50)
    const all = Array.from({ length: d.chunk_count }, (_, i) => ({
      chunk_index: i,
      text: `Nội dung đoạn ${i}`,
      heading_path: ['Báo cáo', `Mục ${i}`],
      page_start: 1,
      page_end: 1,
      content_hash: `hash-${i}`,
    }))
    return HttpResponse.json({
      doc_id: d.doc_id,
      index_version: d.index_version,
      total: all.length,
      offset,
      limit,
      items: all.slice(offset, offset + limit),
    })
  }),

  http.post('/documents/:id/review', ({ params, request }) =>
    HttpResponse.json({
      doc_id: params.id,
      decision: new URL(request.url).searchParams.get('decision'),
    }),
  ),

  http.post('/documents/:id/reindex', ({ params }) =>
    HttpResponse.json({ doc_id: params.id, index_version: 2 }, { status: 202 }),
  ),

  http.post('/documents/:id/cancel', ({ params }) =>
    HttpResponse.json({ doc_id: params.id, cancel_requested: true }, { status: 202 }),
  ),

  http.get('/stats', () => HttpResponse.json(sampleStats())),

  http.get('/temporal/queues', () => HttpResponse.json(sampleQueues())),

  http.post('/search', async ({ request }) => {
    const body = (await request.json()) as { query: string }
    return HttpResponse.json({
      query: body.query,
      model: 'bge-m3',
      results: [
        {
          score: 0.87,
          doc_id: sampleDocs[0].doc_id,
          file_name: sampleDocs[0].file_name,
          index_version: 1,
          chunk_index: 3,
          heading_path: ['Báo cáo', 'Doanh thu'],
          page_start: 2,
          page_end: 2,
          text: 'Doanh thu quý 3 tăng 12%.',
        },
      ],
    })
  }),
]
