import client from './client'

export const authApi = {
  login: (username: string, password: string) => {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    return client.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },
  me: () => client.get('/auth/me'),
}

export const metaApi = {
  parties: () => client.get('/meta/parties'),
  projects: () => client.get('/meta/projects'),
}

export const componentApi = {
  list: (projectId?: number) => client.get('/components', { params: { project_id: projectId } }),
  create: (payload: any) => client.post('/components', payload),
  factoryOut: (payload: any) => client.post('/components/factory-out', payload),
}

export const transportApi = {
  uploadTelemetry: (payload: any) => client.post('/transport/telemetry', payload),
  uploadTelemetryBatch: (payload: any) => client.post('/transport/telemetry/batch', payload),
  alerts: (componentId?: number) => client.get('/transport/alerts', { params: { component_id: componentId } }),
}

export const siteApi = {
  entry: (payload: any) => client.post('/site/entry', payload),
  eligible: () => client.get('/site/hoisting/eligible'),
  hoist: (payload: any) => client.post('/site/hoisting', payload),
  joint: (payload: any) => client.post('/site/joint', payload),
  concealed: (payload: any) => client.post('/site/concealed', payload),
  protection: (payload: any) => client.post('/site/protection', payload),
}

export const traceApi = {
  get: (code: string) => client.get(`/trace/${code}`),
}

export const archiveApi = {
  list: (projectId?: number) => client.get('/archives', { params: { project_id: projectId } }),
  generate: (componentId: number) => client.post(`/archives/generate/${componentId}`),
  submit: (archiveId: number) => client.post(`/archives/${archiveId}/submit`),
  downloadUrl: (archiveId: number) =>
    `${import.meta.env.VITE_API_BASE || ''}/api/archives/${archiveId}/download`,
}

export const syncApi = {
  batch: (payload: any) => client.post('/sync/batch', payload),
}
