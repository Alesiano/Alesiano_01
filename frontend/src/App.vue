<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import logoImg from './assets/logo.png'
import {
  askAIStream, generateImage, getHistory,
  deleteHistory, clearHistory, getConfig,
} from './api/ai'

// ====== 模型 & 尺寸 ======
const aiModels = [
  { value: 'gpt-5.4-mini', label: 'GPT-5.4 Mini' },
  { value: 'gpt-5.4', label: 'GPT-5.4' },
  { value: 'gpt-5.5', label: 'GPT-5.5' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-opus-4-7', label: 'Claude Opus 4.7' },
  { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
]

const imageSizes = [
  { value: '1024x1024', label: '1024x1024' },
  { value: '1024x1536', label: '1024x1536' },
  { value: '1536x1024', label: '1536x1024' },
]

// ====== 对话消息 ======
const messages = ref([])
const inputText = ref('')
const selectedModel = ref(localStorage.getItem('ai_default_model') || 'gpt-5.4-mini')
const isLoading = ref(false)
const errorMsg = ref('')
const chatContainer = ref(null)

// 图片相关
const uploadedImage = ref('')       // base64 data URL（预览用）
const uploadedBase64 = ref('')      // 纯 base64
const uploadedMime = ref('')
const fileInput = ref(null)
const isImageMode = ref(false)      // 生图模式
const imageSize = ref('1024x1024')

// ====== 历史记录 ======
const historyList = ref([])
const historyLoading = ref(false)

// ====== 主题 ======
const isDark = ref(localStorage.getItem('theme') === 'dark')

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
}

// ====== 设置弹窗 ======
const showSettings = ref(false)
const settingsForm = ref({
  apiKey: localStorage.getItem('ai_api_key') || '',
  baseUrl: localStorage.getItem('ai_base_url') || '',
  defaultModel: localStorage.getItem('ai_default_model') || '',
})
const settingsSaved = ref(false)

// ====== 默认配置（从后端获取） ======
const defaultConfig = ref({ api_key_hint: '', base_url: '', default_model: '' })

// ====== 滚动到底部 ======
function scrollToBottom() {
  nextTick(() => {
    const el = chatContainer.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// ====== 发送消息 ======
async function sendMessage() {
  const text = inputText.value.trim()
  const hasText = !!text
  const hasImage = !!uploadedBase64.value
  if ((!hasText && !hasImage && !isImageMode.value) || isLoading.value) return

  // 检测 /image 指令
  let isImageGen = isImageMode.value
  let prompt = text
  if (text.startsWith('/image')) {
    isImageGen = true
    prompt = text.replace(/^\/image\s*/, '')
    if (!prompt) { errorMsg.value = '请输入图片描述'; return }
  }

  errorMsg.value = ''

  if (isImageGen) {
    // 生图
    const userMsg = { role: 'user', content: prompt || '生成图片', isImage: true }
    messages.value.push(userMsg)
    inputText.value = ''
    clearImage()
    isImageMode.value = false
    scrollToBottom()

    isLoading.value = true
    const loadingMsg = { role: 'assistant', content: '', isImage: true, loading: true }
    messages.value.push(loadingMsg)
    scrollToBottom()

    try {
      const res = await generateImage(prompt, imageSize.value)
      const { url, b64_json } = res.data
      const imgUrl = url || (b64_json ? `data:image/png;base64,${b64_json}` : '')
      loadingMsg.loading = false
      loadingMsg.imageUrl = imgUrl
      loadingMsg.content = imgUrl ? '图片已生成' : '生成成功但未返回图片'
      await loadHistory()
    } catch (err) {
      loadingMsg.loading = false
      loadingMsg.content = ''
      loadingMsg.error = err.response?.data?.detail || '生图失败'
    }
  } else {
    // 对话
    const userMsg = { role: 'user', content: text || '请描述这张图片', image: uploadedImage.value }
    messages.value.push(userMsg)
    inputText.value = ''
    const hadImage = !!uploadedBase64.value
    const sentBase64 = uploadedBase64.value
    const sentMime = uploadedMime.value
    clearImage()
    scrollToBottom()

    isLoading.value = true
    const aiMsg = { role: 'assistant', content: '', reasoning: true, streaming: false }
    messages.value.push(aiMsg)
    scrollToBottom()

    try {
      // 提取上下文历史传给 AI
      const history = messages.value.slice(0, -2).filter(m => !m.loading && !m.isImage && !m.error).map(m => ({ role: m.role, content: m.content }))
      const response = await askAIStream(text || '', selectedModel.value, history, sentBase64 || undefined, sentMime || undefined)

      if (!response.ok) {
        let errDetail = `HTTP ${response.status}`
        try {
          const errData = await response.json()
          errDetail = errData.detail || errDetail
        } catch {}
        throw new Error(errDetail)
      }

      aiMsg.loading = false

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          const payload = trimmed.slice(6)
          if (payload === '[DONE]') break
          try {
            const parsed = JSON.parse(payload)
            if (parsed.error) {
              aiMsg.error = parsed.error
              break
            }
            if (parsed.content) {
              // 收到第一条内容时，折叠推理区域，开始打字机输出
              if (aiMsg.reasoning) {
                aiMsg.reasoning = false
                aiMsg.reasoningCollapsed = true
                aiMsg.streaming = true
              }
              aiMsg.content += parsed.content
              scrollToBottom()
            }
          } catch { continue }
        }
      }

      aiMsg.streaming = false
      await loadHistory()
    } catch (err) {
      aiMsg.loading = false
      aiMsg.reasoning = false
      aiMsg.streaming = false
      aiMsg.content = aiMsg.content || ''
      aiMsg.error = err.message || 'AI 请求失败'
    }
  }
  isLoading.value = false
  scrollToBottom()
}

// ====== 输入框键盘 ======
function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

// ====== 图片上传 ======
function triggerUpload() { fileInput.value?.click() }

function compressImage(file) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const objUrl = URL.createObjectURL(file)
    img.onload = () => {
      URL.revokeObjectURL(objUrl)
      const maxSize = 1024
      let { width, height } = img
      if (width > maxSize || height > maxSize) {
        const ratio = Math.min(maxSize / width, maxSize / height)
        width = Math.round(width * ratio)
        height = Math.round(height * ratio)
      }
      const canvas = document.createElement('canvas')
      canvas.width = width; canvas.height = height
      canvas.getContext('2d').drawImage(img, 0, 0, width, height)
      resolve(canvas.toDataURL('image/jpeg', 0.85))
    }
    img.onerror = () => { URL.revokeObjectURL(objUrl); reject(new Error('加载失败')) }
    img.src = objUrl
  })
}

async function handleFileUpload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) { errorMsg.value = '请上传图片文件'; return }
  if (file.size > 10 * 1024 * 1024) { errorMsg.value = '图片不能超过 10MB'; return }
  try {
    const result = await compressImage(file)
    const match = result.match(/^data:(image\/[^;]+);base64,(.+)$/)
    if (!match) { errorMsg.value = '图片读取失败'; return }
    uploadedMime.value = match[1]
    uploadedBase64.value = match[2]
    uploadedImage.value = result
    errorMsg.value = ''
  } catch { errorMsg.value = '图片处理失败' }
  e.target.value = ''
}

async function handlePaste(e) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault()
      const file = item.getAsFile()
      if (file.size > 10 * 1024 * 1024) { errorMsg.value = '图片不能超过 10MB'; continue }
      try {
        const result = await compressImage(file)
        const match = result.match(/^data:(image\/[^;]+);base64,(.+)$/)
        if (!match) continue
        uploadedMime.value = match[1]
        uploadedBase64.value = match[2]
        uploadedImage.value = result
        errorMsg.value = ''
      } catch { errorMsg.value = '图片处理失败' }
      break
    }
  }
}

function clearImage() {
  uploadedImage.value = ''
  uploadedBase64.value = ''
  uploadedMime.value = ''
}

// ====== 历史记录 ======
async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await getHistory()
    historyList.value = res.data
  } finally { historyLoading.value = false }
}

function loadConversation(item) {
  messages.value = []
  if (item.type === 'chat') {
    messages.value.push({ role: 'user', content: item.input_text })
    if (item.output_text) messages.value.push({ role: 'assistant', content: item.output_text })
  } else {
    messages.value.push({ role: 'user', content: item.input_text, isImage: true })
    if (item.image_url) {
      messages.value.push({ role: 'assistant', content: '', isImage: true, imageUrl: item.image_url })
    }
  }
  scrollToBottom()
}

async function handleDeleteHistory(id) {
  await deleteHistory(id)
  await loadHistory()
}

async function handleClearHistory() {
  if (!confirm('确定清空全部历史记录吗？')) return
  await clearHistory()
  await loadHistory()
}

function formatTime(time) {
  if (!time) return ''
  return time.replace('T', ' ').slice(0, 16)
}

function historyTitle(item) {
  const t = item.input_text || ''
  return t.length > 30 ? t.slice(0, 30) + '...' : t
}

// ====== 设置 ======
function openSettings() {
  settingsForm.value.apiKey = localStorage.getItem('ai_api_key') || ''
  settingsForm.value.baseUrl = localStorage.getItem('ai_base_url') || ''
  settingsForm.value.defaultModel = localStorage.getItem('ai_default_model') || ''
  settingsSaved.value = false
  showSettings.value = true
}

function saveSettings() {
  if (settingsForm.value.apiKey) localStorage.setItem('ai_api_key', settingsForm.value.apiKey)
  else localStorage.removeItem('ai_api_key')
  if (settingsForm.value.baseUrl) localStorage.setItem('ai_base_url', settingsForm.value.baseUrl)
  else localStorage.removeItem('ai_base_url')
  if (settingsForm.value.defaultModel) {
    localStorage.setItem('ai_default_model', settingsForm.value.defaultModel)
    selectedModel.value = settingsForm.value.defaultModel
  } else localStorage.removeItem('ai_default_model')
  settingsSaved.value = true
  setTimeout(() => { showSettings.value = false }, 800)
}

// ====== 生命周期 ======
onMounted(async () => {
  // 初始化主题
  const savedTheme = localStorage.getItem('theme') || 'light'
  document.documentElement.setAttribute('data-theme', savedTheme)
  isDark.value = savedTheme === 'dark'

  try {
    const res = await getConfig()
    defaultConfig.value = res.data
  } catch { /* 后端未启动时忽略 */ }
  await loadHistory()
})

// 监听 model 持久化
watch(selectedModel, (v) => {
  localStorage.setItem('ai_default_model', v)
})
</script>

<template>
  <div class="app-layout">
    <!-- ========== 左侧边栏 ========== -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="sidebar-logo">
          <img :src="logoImg" alt="Alesia.AI" class="sidebar-logo-img" width="28" height="28" />
          <span class="sidebar-title">Alesia.AI</span>
        </div>
      </div>

      <div class="sidebar-history">
        <div class="sidebar-section-title">对话历史</div>
        <div v-if="historyLoading" class="sidebar-loading">加载中...</div>
        <div v-else-if="historyList.length === 0" class="sidebar-empty">暂无历史记录</div>
        <div
          v-for="item in historyList"
          :key="item.id"
          class="history-entry"
          @click="loadConversation(item)"
        >
          <div class="history-entry-title">{{ historyTitle(item) }}</div>
          <div class="history-entry-meta">
            <span class="history-entry-tag" :class="item.type">{{ item.type === 'chat' ? '对话' : '生图' }}</span>
            <span class="history-entry-time">{{ formatTime(item.created_at) }}</span>
          </div>
          <button
            class="history-del-btn"
            title="删除"
            @click.stop="handleDeleteHistory(item.id)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
          </button>
        </div>
      </div>

      <div class="sidebar-footer">
        <button class="sidebar-btn sidebar-btn-theme" @click="toggleTheme">
          <svg v-if="!isDark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          {{ isDark ? '浅色模式' : '深色模式' }}
        </button>
        <button
          v-if="historyList.length"
          class="sidebar-btn sidebar-btn-danger"
          @click="handleClearHistory"
        >
          清空历史
        </button>
        <button class="sidebar-btn sidebar-btn-settings" @click="openSettings">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          设置
        </button>
      </div>
    </aside>

    <!-- ========== 右侧主内容区 ========== -->
    <main class="chat-area">
      <!-- 消息流 -->
      <div ref="chatContainer" class="chat-messages">
        <div v-if="messages.length === 0" class="chat-welcome">
          <h1 class="welcome-title">AI 助手</h1>
          <p class="welcome-sub">多模型对话 · 图片理解 · AI 生图</p>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          :class="['message', msg.role === 'user' ? 'message-user' : 'message-ai']"
        >
          <div v-if="msg.role === 'assistant'" class="message-avatar">
            <svg class="avatar-svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div :class="['message-bubble', msg.role === 'user' ? 'bubble-user' : 'bubble-ai']">
            <!-- 用户图片 -->
            <img v-if="msg.role === 'user' && msg.image" :src="msg.image" class="bubble-image" />
            <!-- 生成图片 -->
            <img v-if="msg.isImage && msg.imageUrl" :src="msg.imageUrl" class="bubble-generated-image" />
            <!-- 加载动画 -->
            <div v-if="msg.loading" class="typing-dots"><span></span><span></span><span></span></div>
            <!-- 推理过程（可折叠） -->
            <div
              v-if="msg.role === 'assistant' && (msg.reasoning || msg.reasoningCollapsed)"
              class="reasoning-area"
              :class="{ collapsed: msg.reasoningCollapsed }"
              @click="msg.reasoningCollapsed = !msg.reasoningCollapsed"
            >
              <div class="reasoning-header">
                <span class="reasoning-title">{{ msg.reasoning ? '思考中...' : '推理过程' }}</span>
                <span class="reasoning-toggle">{{ msg.reasoningCollapsed ? '展开' : '收起' }}</span>
              </div>
              <div v-if="msg.reasoning" class="reasoning-dots">
                <span></span><span></span><span></span>
              </div>
            </div>
            <!-- 文本内容 + 光标 -->
            <div v-if="msg.content || msg.streaming" class="bubble-text">
              {{ msg.content }}<span v-if="msg.streaming" class="typing-cursor">|</span>
            </div>
            <!-- 错误 -->
            <div v-if="msg.error" class="bubble-error">{{ msg.error }}</div>
          </div>
        </div>
      </div>

      <!-- 底部输入区 -->
      <div class="chat-input-area">
        <!-- 错误提示 -->
        <div v-if="errorMsg" class="input-error">{{ errorMsg }}</div>

        <!-- 模型选择标签 -->
        <div class="model-tags">
          <button
            v-for="m in aiModels"
            :key="m.value"
            :class="['model-tag', { active: selectedModel === m.value }]"
            @click="selectedModel = m.value"
          >{{ m.label }}</button>
          <button
            :class="['model-tag', 'model-tag-image', { active: isImageMode }]"
            @click="isImageMode = !isImageMode"
            title="AI 生图模式"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
            生图
          </button>
        </div>

        <!-- 生图尺寸选择 -->
        <div v-if="isImageMode" class="image-size-row">
          <span class="size-label">尺寸：</span>
          <button
            v-for="s in imageSizes"
            :key="s.value"
            :class="['size-tag', { active: imageSize === s.value }]"
            @click="imageSize = s.value"
          >{{ s.label }}</button>
        </div>

        <!-- 图片预览 -->
        <div v-if="uploadedImage" class="input-preview">
          <img :src="uploadedImage" alt="预览" />
          <button class="preview-remove" @click="clearImage">&times;</button>
        </div>

        <!-- 输入行 -->
        <div class="input-row">
          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            style="display:none"
            @change="handleFileUpload"
          />
          <button v-if="!isImageMode" class="upload-btn" title="上传图片" @click="triggerUpload">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
          </button>
          <textarea
            v-model="inputText"
            :placeholder="isImageMode ? '描述你想生成的图片...' : '输入消息，或上传/粘贴图片（Enter 发送，Shift+Enter 换行）'"
            rows="1"
            class="input-textarea"
            @keydown="handleKeydown"
            @paste="handlePaste"
          />
          <button
            class="send-btn"
            :disabled="isLoading || (!inputText.trim() && !uploadedBase64 && !isImageMode)"
            @click="sendMessage"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
      </div>
    </main>

    <!-- ========== 设置弹窗 ========== -->
    <div v-if="showSettings" class="modal-overlay" @click.self="showSettings = false">
      <div class="modal">
        <div class="modal-header">
          <h2>设置</h2>
          <button class="modal-close" @click="showSettings = false">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>API 地址</label>
            <input
              v-model="settingsForm.baseUrl"
              type="text"
              placeholder="https://ai.yiqiu.dev/v1"
            />
            <span class="form-hint">后端默认：{{ defaultConfig.base_url || '未获取' }}</span>
          </div>
          <div class="form-group">
            <label>API Key</label>
            <input
              v-model="settingsForm.apiKey"
              type="password"
              placeholder="sk-..."
            />
            <span class="form-hint">后端默认：{{ defaultConfig.api_key_hint || '未配置' }}</span>
          </div>
          <div class="form-group">
            <label>默认模型</label>
            <select v-model="settingsForm.defaultModel">
              <option value="">使用后端默认</option>
              <option v-for="m in aiModels" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </div>
          <div v-if="settingsSaved" class="form-success">设置已保存</div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="showSettings = false">取消</button>
          <button class="btn-save" @click="saveSettings">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
/* ====== CSS 变量体系 ====== */
:root,
[data-theme="light"] {
  --bg-main: #ffffff;
  --bg-sidebar: #fafafa;
  --bg-bubble-user: #f5f5f5;
  --bg-bubble-ai: #ffffff;
  --bg-input: #ffffff;
  --bg-input-row: #f5f5f5;
  --bg-modal: #ffffff;
  --bg-avatar: #f5f5f5;
  --bg-hover: #ededed;
  --bg-sidebar-hover: #ededed;
  --bg-danger-hover: #f5f5f5;
  --text-primary: #000000;
  --text-secondary: #666666;
  --text-muted: #999999;
  --text-placeholder: #999999;
  --border-color: #e0e0e0;
  --border-input: #cccccc;
  --accent: #000000;
  --accent-hover: #333333;
  --danger: #d32f2f;
  --danger-border: #e0e0e0;
  --image-tag-bg: #000000;
  --overlay-bg: rgba(0, 0, 0, 0.25);
  --shadow-modal: 0 8px 32px rgba(0, 0, 0, 0.08);
  --input-row-border: #d5d5d5;
  --input-row-focus-border: #000000;
  --send-btn-bg: #000000;
  --send-btn-hover: #222222;
  --send-btn-icon: #ffffff;
}

[data-theme="dark"] {
  --bg-main: #000000;
  --bg-sidebar: #0a0a0a;
  --bg-bubble-user: #1a1a1a;
  --bg-bubble-ai: #0d0d0d;
  --bg-input: #000000;
  --bg-input-row: #1a1a1a;
  --bg-modal: #141414;
  --bg-avatar: #1a1a1a;
  --bg-hover: #1a1a1a;
  --bg-sidebar-hover: #1a1a1a;
  --bg-danger-hover: #241010;
  --text-primary: #ffffff;
  --text-secondary: #888888;
  --text-muted: #666666;
  --text-placeholder: #666666;
  --border-color: #2a2a2a;
  --border-input: #333333;
  --accent: #ffffff;
  --accent-hover: #cccccc;
  --danger: #f44336;
  --danger-border: #3a2020;
  --image-tag-bg: #ffffff;
  --overlay-bg: rgba(0, 0, 0, 0.7);
  --shadow-modal: 0 8px 32px rgba(0, 0, 0, 0.5);
  --input-row-border: #333333;
  --input-row-focus-border: #ffffff;
  --send-btn-bg: #ffffff;
  --send-btn-hover: #e0e0e0;
  --send-btn-icon: #000000;
}

/* ====== 全局重置 ====== */
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
  background: var(--bg-main);
  color: var(--text-primary);
  overflow: hidden;
  transition: background 0.3s ease, color 0.3s ease;
}

/* ====== 布局 ====== */
.app-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
}

/* ====== 侧边栏 ====== */
.sidebar {
  width: 260px;
  min-width: 260px;
  background: var(--bg-sidebar);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color);
  transition: background 0.3s ease, border-color 0.3s ease;
}

.sidebar-header {
  padding: 20px 18px;
  border-bottom: 1px solid var(--border-color);
  transition: border-color 0.3s ease;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sidebar-logo-img {
  display: block;
  transition: filter 0.3s ease;
}

[data-theme="dark"] .sidebar-logo-img {
  filter: invert(1);
}

.sidebar-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  transition: color 0.3s ease;
}

.sidebar-history {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.sidebar-section-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 8px 8px 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  transition: color 0.3s ease;
}

.sidebar-loading,
.sidebar-empty {
  font-size: 13px;
  color: var(--text-secondary);
  padding: 12px 8px;
  text-align: center;
}

/* 历史条目 */
.history-entry {
  position: relative;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  transition: background 0.15s;
}

.history-entry:hover {
  background: var(--bg-sidebar-hover);
}

.history-entry:hover .history-del-btn {
  opacity: 1;
}

.history-entry-title {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 24px;
  transition: color 0.3s ease;
}

.history-entry-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.history-entry-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  color: #fff;
}

.history-entry-tag.chat { background: #000; }
.history-entry-tag.image { background: #000; }

.history-entry-time {
  font-size: 11px;
  color: var(--text-secondary);
  transition: color 0.3s ease;
}

.history-del-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0;
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: opacity 0.15s, color 0.15s;
}

.history-del-btn:hover {
  color: var(--danger);
}

/* 侧边栏底部 */
.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.3s ease;
}

.sidebar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-input);
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, color 0.3s ease, border-color 0.3s ease;
}

.sidebar-btn:hover { background: var(--bg-sidebar-hover); }
.sidebar-btn-danger:hover { background: var(--bg-danger-hover); color: var(--danger); border-color: var(--danger-border); }

.sidebar-btn-theme { border-color: var(--border-input); }
.sidebar-btn-theme:hover { border-color: var(--text-primary); color: var(--text-primary); }

.sidebar-btn-settings { border-color: var(--border-input); }
.sidebar-btn-settings:hover { border-color: var(--text-primary); color: var(--text-primary); }

/* ====== 主内容区 ====== */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-main);
  transition: background 0.3s ease;
}

/* 消息区域 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px;
  scroll-behavior: smooth;
}

/* 欢迎页 */
.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
}

.welcome-title {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  transition: color 0.3s ease;
}

.welcome-sub {
  font-size: 14px;
  color: var(--text-secondary);
  transition: color 0.3s ease;
}

/* 消息气泡 */
.message {
  display: flex;
  gap: 14px;
  margin-bottom: 24px;
  max-width: 85%;
}

.message-user {
  margin-left: auto;
  flex-direction: row-reverse;
}

.message-ai {
  margin-right: auto;
}

.message-avatar {
  width: 30px;
  height: 30px;
  border-radius: 4px;
  background: var(--bg-avatar);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
  transition: background 0.3s ease;
}

.avatar-svg {
  color: #000;
  transition: color 0.3s ease;
}

[data-theme="dark"] .avatar-svg {
  color: #fff;
}

.bubble-user {
  background: var(--bg-bubble-user);
  border-radius: 18px 18px 4px 18px;
  transition: background 0.3s ease;
}

.bubble-ai {
  background: var(--bg-bubble-ai);
  border-radius: 18px 18px 18px 4px;
  transition: background 0.3s ease;
}

.bubble-text {
  font-size: 14px;
  line-height: 1.65;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  transition: color 0.3s ease;
}

.message-bubble {
  padding: 16px 20px;
  max-width: 100%;
}

.bubble-image {
  max-width: 240px;
  max-height: 240px;
  border-radius: 8px;
  margin-bottom: 8px;
  display: block;
}

.bubble-generated-image {
  max-width: 400px;
  max-height: 400px;
  border-radius: 8px;
  margin-bottom: 8px;
  display: block;
}

.bubble-error {
  color: var(--danger);
  font-size: 13px;
}

/* 打字动画 */
.typing-dots {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.typing-dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: typing 1.4s infinite ease-in-out both;
}

.typing-dots span:nth-child(1) { animation-delay: -0.32s; }
.typing-dots span:nth-child(2) { animation-delay: -0.16s; }
.typing-dots span:nth-child(3) { animation-delay: 0s; }

@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ====== 推理过程区域 ====== */
.reasoning-area {
  background: var(--bg-input-row);
  border-radius: 12px;
  padding: 12px 16px;
  margin-bottom: 12px;
  cursor: pointer;
  user-select: none;
  transition: background 0.3s ease;
}

.reasoning-area:hover {
  background: var(--bg-hover);
}

.reasoning-area.collapsed .reasoning-dots {
  display: none;
}

.reasoning-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.reasoning-title {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
  transition: color 0.3s ease;
}

.reasoning-toggle {
  font-size: 11px;
  color: var(--text-muted);
  transition: color 0.3s ease;
}

/* 思考动画：三个点依次淡入淡出 */
.reasoning-dots {
  display: flex;
  gap: 6px;
  padding: 6px 0 2px;
}

.reasoning-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: reasoning-breathe 1.2s infinite ease-in-out both;
}

.reasoning-dots span:nth-child(1) { animation-delay: 0s; }
.reasoning-dots span:nth-child(2) { animation-delay: 0.3s; }
.reasoning-dots span:nth-child(3) { animation-delay: 0.6s; }

@keyframes reasoning-breathe {
  0%, 100% { opacity: 0.2; transform: scale(0.7); }
  50% { opacity: 1; transform: scale(1); }
}

/* 打字机光标闪烁 */
.typing-cursor {
  display: inline;
  font-weight: 300;
  color: var(--text-primary);
  animation: blink-cursor 0.5s step-end infinite;
}

@keyframes blink-cursor {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* ====== 输入区 ====== */
.chat-input-area {
  padding: 16px 40px 24px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-main);
  transition: background 0.3s ease, border-color 0.3s ease;
}

.input-error {
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 8px;
}

/* 模型标签 */
.model-tags {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.model-tag {
  padding: 8px 16px;
  font-size: 13px;
  border-radius: 20px;
  border: 1px solid var(--border-input);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 5px;
  font-weight: 500;
}

.model-tag:hover { border-color: var(--text-primary); color: var(--text-primary); }
.model-tag.active { background: #000; border-color: #000; color: #fff; }
.model-tag-image.active { background: #000; border-color: #000; color: #fff; }

/* 生图尺寸 */
.image-size-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.size-label { font-size: 12px; color: var(--text-secondary); transition: color 0.3s ease; }

.size-tag {
  padding: 5px 14px;
  font-size: 12px;
  border-radius: 16px;
  border: 1px solid var(--border-input);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.size-tag:hover { border-color: var(--text-primary); color: var(--text-primary); }
.size-tag.active { background: #000; border-color: #000; color: #fff; }

/* 图片预览 */
.input-preview {
  display: inline-flex;
  position: relative;
  margin-bottom: 8px;
}

.input-preview img {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid var(--border-input);
  transition: border-color 0.3s ease;
}

.preview-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: var(--border-input);
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  transition: background 0.15s;
}

.preview-remove:hover { background: var(--danger); color: #fff; }

/* 输入行 */
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: var(--bg-input-row);
  border: 1px solid var(--input-row-border);
  border-radius: 28px;
  padding: 8px 10px 8px 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  transition: border-color 0.2s, background 0.3s ease, box-shadow 0.2s;
}

.input-row:focus-within {
  border-color: var(--input-row-focus-border);
  box-shadow: 0 1px 6px rgba(0,0,0,0.08);
}

.upload-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  transition: color 0.2s;
  flex-shrink: 0;
}

.upload-btn:hover { color: var(--text-primary); }

.input-textarea {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  padding: 8px 4px;
  line-height: 1.5;
  max-height: 160px;
  overflow-y: auto;
  transition: color 0.3s ease;
}

.input-textarea::placeholder { color: var(--text-placeholder); }

.send-btn {
  background: var(--send-btn-bg);
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--send-btn-icon);
  flex-shrink: 0;
  transition: background 0.2s, transform 0.15s;
}

.send-btn:hover { background: var(--send-btn-hover); transform: scale(1.04); }
.send-btn:disabled { opacity: 0.3; cursor: not-allowed; transform: none; }

/* ====== 设置弹窗 ====== */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  transition: background 0.3s ease;
}

.modal {
  background: var(--bg-modal);
  border-radius: 12px;
  width: 440px;
  max-width: 90vw;
  box-shadow: var(--shadow-modal);
  transition: background 0.3s ease, box-shadow 0.3s ease;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 0;
}

.modal-header h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  transition: color 0.3s ease;
}

.modal-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 24px;
  cursor: pointer;
  line-height: 1;
}

.modal-close:hover { color: var(--text-primary); }

.modal-body {
  padding: 20px 24px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 6px;
  transition: color 0.3s ease;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-input);
  border-radius: 8px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s, background 0.3s ease, color 0.3s ease;
}

.form-group input:focus,
.form-group select:focus {
  border-color: var(--text-primary);
}

.form-group select {
  appearance: none;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238e8e8e' stroke-width='2'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 36px;
}

.form-hint {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
  transition: color 0.3s ease;
}

.form-success {
  color: #000;
  font-size: 13px;
  text-align: center;
  padding: 8px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 24px 20px;
}

.btn-cancel {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid var(--border-input);
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, color 0.3s ease, border-color 0.3s ease;
}

.btn-cancel:hover { background: var(--bg-hover); }

.btn-save {
  padding: 8px 20px;
  border-radius: 6px;
  border: none;
  background: #000;
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.btn-save:hover { background: #333; }
</style>
