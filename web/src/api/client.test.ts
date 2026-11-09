import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { api, ApiError, profileFields } from './client'

describe('profileFields', () => {
  it.each([
    ['v2', true, 2],
    ['v1', true, 1],
    ['legacy', false, 2],
  ] as const)('%s', (profile, extract_media, pipeline_version) => {
    expect(profileFields(profile)).toEqual({ extract_media, pipeline_version })
  })
})

describe('api client', () => {
  it('listDocuments gửi status nhiều giá trị cách nhau bằng dấu phẩy', async () => {
    let seen = ''
    server.use(
      http.get('/documents', ({ request }) => {
        seen = new URL(request.url).search
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
      }),
    )
    await api.listDocuments({ status: ['CONVERTING', 'INDEXING'], q: 'hợp đồng', offset: 20 })
    const sp = new URLSearchParams(seen)
    expect(sp.get('status')).toBe('CONVERTING,INDEXING')
    expect(sp.get('q')).toBe('hợp đồng')
    expect(sp.get('offset')).toBe('20')
    expect(sp.has('limit')).toBe(false)
  })

  it('upload gửi field theo profile', async () => {
    // FormData của jsdom không đi qua fetch của Node được, nên bắt lời gọi fetch để đọc body.
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(Response.json({ duplicate: false }, { status: 202 }))
    await api.upload(new File(['x'], 'a.pdf'), 'legacy')
    const [url, init] = spy.mock.calls[0]
    const form = init?.body as FormData
    expect(url).toBe('/documents')
    expect(init?.method).toBe('POST')
    expect({
      extract_media: form.get('extract_media'),
      pipeline_version: form.get('pipeline_version'),
      name: (form.get('file') as File).name,
    }).toEqual({ extract_media: 'false', pipeline_version: '2', name: 'a.pdf' })
    spy.mockRestore()
  })

  it('lỗi {code, detail} thành ApiError', async () => {
    server.use(
      http.post('/search', () =>
        HttpResponse.json({ code: 'SEARCH_UNAVAILABLE', detail: 'Qdrant lỗi' }, { status: 503 }),
      ),
    )
    const err = await api.search({ query: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 503, code: 'SEARCH_UNAVAILABLE', detail: 'Qdrant lỗi' })
  })

  it('lỗi {detail} không có code', async () => {
    const err = await api.getDocument('khong-co').catch((e) => e)
    expect(err).toMatchObject({ status: 404, code: null, detail: 'Không tìm thấy tài liệu' })
  })

  it('detail dạng mảng (422 của FastAPI) được chuyển thành chuỗi', async () => {
    server.use(
      http.get('/documents', () =>
        HttpResponse.json({ detail: [{ msg: 'sai' }] }, { status: 422 }),
      ),
    )
    const err = await api.listDocuments().catch((e) => e)
    expect(err.detail).toContain('sai')
  })

  it('thân lỗi không phải JSON thì dùng status text', async () => {
    server.use(http.get('/stats', () => new HttpResponse('boom', { status: 500 })))
    const err = await api.getStats().catch((e) => e)
    expect(err).toMatchObject({ status: 500, code: null })
  })

  it('mất kết nối thành ApiError status 0', async () => {
    server.use(http.get('/stats', () => HttpResponse.error()))
    const err = await api.getStats().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 0, code: 'NETWORK' })
  })

  it('getMarkdown trả text, rawUrl mã hoá id', async () => {
    expect(await api.getMarkdown('a'.repeat(64))).toContain('# Tiêu đề')
    expect(api.rawUrl('a b')).toBe('/documents/a%20b/raw')
  })

  it('review gửi decision trên query', async () => {
    const res = await api.review('x', 'reject')
    expect(res.decision).toBe('reject')
  })
})
