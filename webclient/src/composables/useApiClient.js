import { ref } from 'vue'
import axios from 'axios'

// Use relative /api by default so Vite dev proxy can handle CORS in development.
// In production, set VITE_API_URL to the full backend URL.
const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'
const STORAGE_KEY = 'openscrum_session_id'

const sessionId = ref(null)
const modelName = ref('')

// AbortController for canceling ongoing requests
let currentAbortController = null

// Load session ID from localStorage
function loadSessionId() {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      sessionId.value = stored
    }
  }
}

// Save session ID to localStorage
function saveSessionId(id) {
  if (typeof window !== 'undefined') {
    if (id) {
      localStorage.setItem(STORAGE_KEY, id)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }
}

// Initialize from localStorage
loadSessionId()

export function useApiClient() {
  const client = axios.create({
    baseURL: API_BASE_URL,
    timeout: 300000, // 5 minutes for long operations
  })

  const health = async () => {
    try {
      const response = await client.get('/health')
      modelName.value = response.data.model || 'unknown'
      return response.data
    } catch (error) {
      console.error('Health check failed:', error)
      throw error
    }
  }

  const listSessions = async (params = {}) => {
    try {
      const response = await client.get('/sessions', { params })
      return response.data
    } catch (error) {
      console.error('Failed to list sessions:', error)
      return []
    }
  }

  const updateSession = async (id, updates) => {
    try {
      const response = await client.patch(`/sessions/${id}`, updates)
      return response.data
    } catch (error) {
      console.error('Failed to update session:', error)
      throw error
    }
  }

  const deleteSession = async (id) => {
    try {
      const response = await client.delete(`/sessions/${id}`)
      return response.data
    } catch (error) {
      console.error('Failed to delete session:', error)
      throw error
    }
  }

  const getSession = async (id) => {
    try {
      const response = await client.get(`/sessions/${id}`)
      return response.data
    } catch (error) {
      console.error('Failed to get session:', error)
      throw error
    }
  }

  const createSession = async (workspaceName = null, title = null) => {
    try {
      // Title is required - use provided title or fallback to workspaceName
      const sessionTitle = title || workspaceName
      if (!sessionTitle) {
        throw new Error('Session title is required')
      }

      const data = {
        title: sessionTitle,
      }

      // workspace_name is kept for API compatibility but ignored by server
      if (workspaceName) {
        data.workspace_name = workspaceName
      }

      const response = await client.post('/sessions', data, {
        headers: { 'Content-Type': 'application/json' },
      })

      const newSessionId = response.data.id
      sessionId.value = newSessionId
      saveSessionId(newSessionId)
      return response.data
    } catch (error) {
      console.error('Failed to create session:', error)
      if (error.response) {
        console.error('Response data:', error.response.data)
      }
      sessionId.value = null
      saveSessionId(null)
      throw error
    }
  }

  const setSession = (id) => {
    sessionId.value = id
    saveSessionId(id)
  }

  const clearSession = () => {
    sessionId.value = null
    saveSessionId(null)
  }

  const sendMessage = async (message, mode = 'plan', onChunk = null) => {
    const requestData = {
      message,
      mode,
    }

    let endpoint
    if (sessionId.value) {
      endpoint = `/sessions/${sessionId.value}/message`
    } else {
      endpoint = '/chat'
      // For stateless mode, use current directory as workspace
      requestData.workspace_root = window.location.pathname || ''
    }

    // Create new AbortController for this request
    currentAbortController = new AbortController()

    try {
      // Use relative path - fetch resolves against current origin; avoid new URL() with /api base
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData),
        signal: currentAbortController.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`HTTP ${response.status}: ${errorText}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (onChunk) {
                await onChunk(data)
              }
            } catch (e) {
              console.error('Failed to parse SSE chunk:', e, line)
            }
          }
        }
      }
    } catch (error) {
      // Don't log abort errors as errors - they're expected
      if (error.name === 'AbortError') {
        console.log('Request aborted by user')
        return // Don't throw on abort
      }
      console.error('Error sending message:', error)
      throw error
    } finally {
      currentAbortController = null
    }
  }

  const abortCurrentRequest = () => {
    if (currentAbortController) {
      console.log('Aborting current request...')
      currentAbortController.abort()
      currentAbortController = null
    }
  }

  const getSessionMessages = async (id, limit = null) => {
    try {
      const params = limit ? { limit } : {}
      const response = await client.get(`/sessions/${id}/messages`, { params })
      return response.data
    } catch (error) {
      console.error('Failed to get session messages:', error)
      throw error
    }
  }

  const compressContext = async (id) => {
    try {
      const response = await client.post(`/sessions/${id}/compress`)
      return response.data
    } catch (error) {
      console.error('Failed to compress context:', error)
      throw error
    }
  }

  const resetContext = async (id) => {
    try {
      const response = await client.post(`/sessions/${id}/reset`)
      return response.data
    } catch (error) {
      console.error('Failed to reset context:', error)
      throw error
    }
  }

  const resetSession = async (id) => {
    try {
      const response = await client.post(`/sessions/${id}/reset-session`)
      return response.data
    } catch (error) {
      console.error('Failed to reset session:', error)
      throw error
    }
  }

  const abortSession = async (id) => {
    try {
      const response = await client.post(`/sessions/${id}/abort`)
      return response.data
    } catch (error) {
      console.error('Failed to abort session:', error)
      throw error
    }
  }

  const replyToPermission = async (requestId, reply) => {
    try {
      const response = await client.post(`/permissions/${requestId}/reply`, {
        reply,
      })
      return response.data
    } catch (error) {
      console.error('Failed to reply to permission:', error)
      throw error
    }
  }

  const getTokenUsage = async (id) => {
    try {
      const response = await client.get(`/sessions/${id}/token-usage`)
      return response.data
    } catch (error) {
      console.error('Failed to get token usage:', error)
      // Return default values on error
      return {
        token_count: 0,
        token_limit: 128000,
        usage_percentage: 0,
        should_compress: false,
        model: 'gpt-4',
        message_count: 0,
      }
    }
  }

  const analyzeWorkspace = async (id) => {
    try {
      const response = await client.get(`/sessions/${id}/workspace/analyze`)
      return response.data
    } catch (error) {
      console.error('Failed to analyze workspace:', error)
      return {
        has_code: false,
        has_design_docs: false,
        error: error.message
      }
    }
  }

  const fetchSyncStatus = async (id) => {
    try {
      const response = await client.get(`/sessions/${id}/workspace/sync-status`)
      return response.data
    } catch (error) {
      console.error('Failed to get workspace sync status:', error)
      return {
        is_synced: false,
        warnings: [],
        error: error.message
      }
    }
  }

  const triggerWorkspaceSync = async (id) => {
    try {
      const response = await client.post(`/sessions/${id}/workspace/sync`)
      return response.data
    } catch (error) {
      console.error('Failed to trigger workspace sync:', error)
      return {
        success: false,
        error: error.message
      }
    }
  }

  const fetchWorkspaceTree = async (id) => {
    try {
      const response = await client.get(`/sessions/${id}/workspace/tree`)
      return response.data
    } catch (error) {
      console.error('Failed to get workspace tree:', error)
      return {
        name: "root",
        type: "directory",
        children: []
      }
    }
  }

  const fetchWorkspaceFile = async (id, path) => {
    try {
      const response = await client.get(`/sessions/${id}/workspace/file`, {
        params: { path }
      })
      return response.data.content
    } catch (error) {
      console.error('Failed to get workspace file:', error)
      throw error
    }
  }

  const saveWorkspaceFile = async (id, path, content) => {
    try {
      const response = await client.put(`/sessions/${id}/workspace/file`, {
        path,
        content
      })
      return response.data
    } catch (error) {
      console.error('Failed to save workspace file:', error)
      throw error
    }
  }

  const fetchTodos = async (id) => {
    try {
      const response = await client.get(`/sessions/${id}/todo`)
      return response.data || []
    } catch (error) {
      console.error('Failed to fetch todos:', error)
      return []
    }
  }

  const updateTodos = async (id, todos) => {
    try {
      const response = await client.put(`/sessions/${id}/todo`, todos)
      return response.data || []
    } catch (error) {
      console.error('Failed to update todos:', error)
      return todos // Return old on failure?
    }
  }

  const generateTodos = async (id) => {
    try {
      const response = await client.post(`/sessions/${id}/todo/generate`)
      return response.data || []
    } catch (error) {
      console.error('Failed to generate todos:', error)
      return []
    }
  }

  return {
    health,
    listSessions,
    updateSession,
    deleteSession,
    getSession,
    getSessionMessages,
    createSession,
    setSession,
    clearSession,
    sendMessage,
    abortCurrentRequest,
    replyToPermission,
    compressContext,
    resetContext,
    resetSession,
    abortSession,
    getTokenUsage,
    analyzeWorkspace,
    fetchSyncStatus,
    triggerWorkspaceSync,
    fetchWorkspaceTree,
    fetchWorkspaceFile,
    saveWorkspaceFile,
    fetchTodos,
    updateTodos,
    generateTodos,
    sessionId,
    modelName,
  }
}
