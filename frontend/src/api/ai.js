import axios from 'axios'

// 部署后通过环境变量 VITE_API_BASE_URL 指向后端（如 https://xxx.railway.app）
// 开发时 Vite proxy 会将 /api 转发到 localhost:8080，无需设置此变量
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || ''

const api = axios.create({
  baseURL: apiBaseUrl ? `${apiBaseUrl}/api` : '/api',
  maxBodyLength: Infinity,
  maxContentLength: Infinity,
  timeout: 120000,
})

// 每次请求自动注入前端配置的 API Key 和 Base URL
api.interceptors.request.use(config => {
  const apiKey = localStorage.getItem('ai_api_key')
  const baseUrl = localStorage.getItem('ai_base_url')
  if (apiKey) config.headers['X-Api-Key'] = apiKey
  if (baseUrl) config.headers['X-Api-Base-Url'] = baseUrl
  return config
})

export function askAIStream(message, model, history, image, imageMime) {
  const apiKey = localStorage.getItem('ai_api_key')
  const baseUrl = localStorage.getItem('ai_base_url')
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || ''

  const headers = { 'Content-Type': 'application/json' }
  if (apiKey) headers['X-Api-Key'] = apiKey
  if (baseUrl) headers['X-Api-Base-Url'] = baseUrl

  const url = apiBaseUrl ? `${apiBaseUrl}/api/chat` : '/api/chat'

  return fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      message,
      model,
      history: history || [],
      image: image || undefined,
      image_mime: imageMime || undefined,
    }),
  })
}

export function generateImage(prompt, size = '1024x1024') {
  return api.post('/image', { prompt, size })
}

export function getHistory() {
  return api.get('/history')
}

export function deleteHistory(id) {
  return api.delete(`/history/${id}`)
}

export function clearHistory() {
  return api.delete('/history')
}

export function getConfig() {
  return api.get('/config')
}

export function updateConfig(data) {
  return api.post('/config', data)
}
