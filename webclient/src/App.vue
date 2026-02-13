<template>
  <div class="min-h-screen bg-background dark-mode">
    <div class="flex flex-col h-screen">
      <!-- Header -->
      <header class="border-b border-surface-dark px-6 py-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <button
              @click="handleExitSession"
              class="px-3 py-1.5 text-sm rounded-lg bg-surface-dark hover:bg-surface-dark/80 transition-colors text-text-inverse"
              title="Exit Session"
            >
              Exit Session
            </button>
            <h1 class="text-xl font-semibold text-text-inverse">OpenScrum Agent</h1>
            <span v-if="modelName" class="text-sm text-text-muted">
              {{ modelName }}
            </span>
            <span v-if="currentSession" class="text-xl font-semibold text-cyan-400">
              {{ sessionDisplayName }}
            </span>
          </div>
          <div class="flex items-center gap-4">
            <span class="text-sm text-text-muted">
              Mode: <span class="font-medium">{{ mode === 'plan' ? 'Plan' : 'Edit' }}</span>
            </span>
            <button
              @click="toggleMode"
              class="px-3 py-1.5 text-sm rounded-lg bg-surface-dark hover:bg-surface-dark/80 transition-colors"
            >
              Switch to {{ mode === 'plan' ? 'Edit' : 'Plan' }}
            </button>
            <button
              @click="handleCompressContext"
              :disabled="!sessionId || messages.length === 0"
              class="px-3 py-1.5 text-sm rounded-lg bg-surface-dark hover:bg-surface-dark/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Compress conversation history to reduce context size"
            >
              Compress Context
            </button>
            <button
              @click="handleResetContext"
              :disabled="!sessionId || messages.length === 0"
              class="px-3 py-1.5 text-sm rounded-lg bg-red-600 hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Clear all conversation history (cannot be undone)"
            >
              Reset Context
            </button>
          </div>
        </div>
      </header>

      <!-- Split View Container -->
      <div v-if="!isInitializing && !showSessionSelector" class="flex-1 flex overflow-hidden split-container">
        <!-- Left Pane - Chat -->
        <div class="flex flex-col border-r border-surface-dark" :style="{ width: leftPaneWidth + '%' }">
          <!-- Chat Messages Area -->
          <main class="flex-1 overflow-y-auto custom-scrollbar px-6 py-4">
            <div class="space-y-4 max-w-4xl">
              <!-- Welcome message -->
              <div v-if="messages.length === 0" class="text-center py-12">
                <p class="text-text-muted text-lg">Start a conversation with the OpenScrum Agent</p>
                <p class="text-text-muted text-sm mt-2">Type your message below and press Enter to send</p>
              </div>

              <!-- Messages - All aligned left -->
              <div
                v-for="(message, index) in messages"
                :key="index"
                class="flex justify-start"
              >
                <div :class="[
                  'max-w-[85%]',
                  message.role === 'user' ? 'message-user' : 'message-agent'
                ]">
                  <div v-if="message.role === 'agent'" class="prose prose-invert max-w-none">
                    <!-- Check if message contains progress JSON -->
                    <template v-if="extractProgressData(message.content)">
                      <ProgressTracker 
                        :plan="extractProgressData(message.content).plan"
                        :currentProgress="extractProgressData(message.content).current_progress"
                      />
                    </template>
                    <div v-else v-html="marked.parse(formatMessageContent(message.content))"></div>
                  </div>
                  <div v-else class="whitespace-pre-wrap">{{ message.content }}</div>
                </div>
              </div>

              <!-- Thinking/Working indicator -->
              <div v-if="isThinking" class="flex justify-start">
                <div class="message-agent flex items-start gap-3">
                  <div class="relative mt-1">
                    <div class="animate-spin h-5 w-5 border-2 border-accent border-t-transparent rounded-full"></div>
                  </div>
                  <div class="flex flex-col gap-1">
                    <span class="text-text-inverse font-medium">{{ thinkingMessage }}</span>
                    <span v-if="currentTool" class="text-xs text-accent">Executing: {{ currentTool }}</span>
                    <pre v-if="currentToolCommand" class="text-xs text-text-muted bg-background-dark px-2 py-1 rounded mt-1 overflow-x-auto">{{ currentToolCommand }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </main>

          <!-- Input Area -->
          <footer class="border-t border-surface-dark px-6 py-4">
            <div class="flex flex-col gap-2 max-w-4xl">
              <!-- Markdown Preview -->
              <div v-if="inputMessage.trim()" class="bg-surface-dark rounded-lg p-3 border border-surface max-h-32 overflow-y-auto custom-scrollbar">
                <div class="prose prose-sm prose-invert max-w-none" v-html="marked.parse(inputMessage)"></div>
              </div>
              
              <!-- Input Box -->
              <div class="flex gap-3">
                <textarea
                  v-model="inputMessage"
                  @keydown.enter.exact.prevent="sendMessage"
                  @keydown.shift.enter.exact="inputMessage += '\n'"
                  placeholder="Type your message with markdown support... (Enter to send, Shift+Enter for newline)"
                  :disabled="!sessionId"
                  class="flex-1 px-4 py-3 bg-accent text-text-inverse rounded-2xl border-none focus:outline-none focus:ring-2 focus:ring-accent-hover resize-none custom-scrollbar disabled:opacity-50 disabled:cursor-not-allowed placeholder-text-inverse/60"
                  rows="5"
                  ref="inputRef"
                ></textarea>
                <button
                  @click="sendMessage"
                  :disabled="!inputMessage.trim() || isSending || !sessionId"
                  class="px-6 py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium transition-colors self-end"
                >
                  Send
                </button>
              </div>
            </div>
          </footer>
        </div>

        <!-- Draggable Divider -->
        <div 
          @mousedown="startDragging"
          class="w-1 bg-surface-dark hover:bg-accent cursor-col-resize transition-colors flex-shrink-0"
          :class="{ 'bg-accent': isDragging }"
        ></div>

        <!-- Right Pane - Split into top and bottom -->
        <div class="flex flex-col bg-surface/30 right-pane" :style="{ width: (100 - leftPaneWidth) + '%' }">
          <!-- Top Section - Empty for now -->
          <div class="bg-surface/30 border-b border-surface-dark" :style="{ height: rightTopHeight + '%' }">
            <!-- Empty pane - placeholder for future content -->
          </div>
          
          <!-- Vertical Draggable Divider -->
          <div 
            @mousedown="startDraggingVertical"
            class="h-1 bg-surface-dark hover:bg-accent cursor-row-resize transition-colors flex-shrink-0"
            :class="{ 'bg-accent': isDraggingVertical }"
          ></div>
          
          <!-- Bottom Section - Tool List and Output -->
          <div class="flex overflow-hidden" :style="{ height: (100 - rightTopHeight) + '%' }">
            <!-- Tool List -->
            <div class="w-1/2 border-r border-surface-dark">
              <ToolList 
                :tools="toolExecutions" 
                :selectedTool="selectedTool"
                @select="handleSelectTool"
              />
            </div>
            
            <!-- Tool Output -->
            <div class="w-1/2">
              <ToolOutput :tool="selectedTool" />
            </div>
          </div>
        </div>
      </div>

      <!-- Session Selector Dialog -->
      <SessionSelector
        v-if="showSessionSelector"
        :canClose="!!sessionId"
        @select="handleSelectSession"
        @create="handleCreateSession"
        @close="showSessionSelector = false"
      />

      <!-- Permission Dialog -->
      <PermissionDialog
        v-if="pendingPermission"
        :permission="pendingPermission"
        @reply="handlePermissionReply"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApiClient } from './composables/useApiClient'
import SessionSelector from './components/SessionSelector.vue'
import PermissionDialog from './components/PermissionDialog.vue'
import ProgressTracker from './components/ProgressTracker.vue'
import ToolList from './components/ToolList.vue'
import ToolOutput from './components/ToolOutput.vue'
import { marked } from 'marked'
import hljs from 'highlight.js'

const { 
  health, 
  listSessions,
  getSession,
  getSessionMessages,
  createSession, 
  setSession,
  clearSession,
  sendMessage: apiSendMessage,
  replyToPermission,
  compressContext,
  resetContext,
  sessionId,
  modelName 
} = useApiClient()

const mode = ref('plan')
const inputMessage = ref('')
const messages = ref([])
const isThinking = ref(false)
const thinkingMessage = ref('Thinking...')
const currentTool = ref(null)
const currentToolCommand = ref(null)
const isSending = ref(false)
const inputRef = ref(null)
const showSessionSelector = ref(false)
const currentSession = ref(null)
const isInitializing = ref(true)
const pendingPermission = ref(null)
const permissionResolve = ref(null)

// Resizable panes state
const leftPaneWidth = ref(66.67) // 2/3 of screen width in percentage
const isDragging = ref(false)
const rightTopHeight = ref(33.33) // 1/3 of right pane height in percentage
const isDraggingVertical = ref(false)

// Tool execution tracking
const toolExecutions = ref([])
const selectedTool = ref(null)

// Display name: prefer session.title from server, fallback to 'Untitled Session'
const sessionDisplayName = computed(() => {
  const s = currentSession.value
  if (!s) return ''
  return (s.title && s.title.trim()) || 'Untitled Session'
})

// Helper to extract tool executions from message history
const extractToolExecutions = (messageHistory) => {
  const tools = []
  
  for (const msg of messageHistory) {
    const parts = msg.parts || []
    for (const part of parts) {
      // Check if it's a tool part
      if (part.type === 'tool' && part.state) {
        const state = part.state
        tools.push({
          name: part.tool || state.title || 'unknown',
          input: state.input || null,
          output: state.output || null,
          status: state.status || 'pending',
          timestamp: state.time?.start || msg.info?.time?.created || Date.now()
        })
      }
    }
  }
  
  return tools
}

// Auto-calculate optimal chat pane width based on content
const calculateOptimalChatWidth = () => {
  // If there are tool executions, give more space to the right pane
  if (toolExecutions.value.length > 0) {
    // With tools: 60% chat, 40% for tools panel
    return 60
  }
  
  // If there are messages but no tool executions yet
  if (messages.value.length > 0) {
    // Calculate average message length to determine if we need more width
    const totalLength = messages.value.reduce((sum, msg) => sum + (msg.content?.length || 0), 0)
    const avgLength = totalLength / messages.value.length
    
    // If messages are long/complex (avg > 500 chars), give more space to chat
    if (avgLength > 500) {
      return 70
    }
    
    // Medium complexity messages
    return 66.67
  }
  
  // Empty session or new session: default to 70% for chat
  return 70
}

// Configure marked for markdown rendering
marked.setOptions({
  highlight: function(code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext'
    return hljs.highlight(code, { language }).value
  },
  breaks: true,
  gfm: true,
})

// Helper to extract progress JSON from content
const extractProgressData = (content) => {
  if (!content) return null
  
  const trimmed = content.trim()
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed)
      // Check if it has the progress structure
      if (parsed.plan && parsed.current_progress) {
        return parsed
      }
    } catch (e) {
      // Not valid JSON
    }
  }
  return null
}

// Helper to format message content - wrap JSON in code blocks
const formatMessageContent = (content) => {
  if (!content) return ''
  
  // Check if it's progress JSON - don't format it, we'll show it as a component
  if (extractProgressData(content)) {
    return '' // Return empty string, we'll handle it separately
  }
  
  // Check if content looks like JSON (starts with { or [, and contains proper JSON structure)
  const trimmed = content.trim()
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || 
      (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      // Try to parse as JSON
      const parsed = JSON.parse(trimmed)
      // If successful, wrap in markdown code block
      const formatted = JSON.stringify(parsed, null, 2)
      return '```json\n' + formatted + '\n```'
    } catch (e) {
      // Not valid JSON, return as-is
      return content
    }
  }
  
  return content
}

const toggleMode = () => {
  mode.value = mode.value === 'plan' ? 'edit' : 'plan'
}

const handleCompressContext = async () => {
  if (!sessionId.value || messages.value.length === 0) return
  
  if (!confirm('Compress conversation history? This will summarize older messages to reduce context size.')) {
    return
  }
  
  try {
    await compressContext(sessionId.value)
    // Reload messages after compression
    const messageHistory = await getSessionMessages(sessionId.value)
    
    // Extract tool executions from remaining messages
    toolExecutions.value = extractToolExecutions(messageHistory)
    selectedTool.value = null
    
    // Convert messages (server returns newest first, so reverse)
    messages.value = messageHistory.reverse().map(msg => {
      const info = msg.info
      const role = info.role === 'user' ? 'user' : 'agent'
      let content = ''
      if (msg.parts && msg.parts.length > 0) {
        content = msg.parts
          .filter(part => part.type === 'text')
          .map(part => part.text)
          .join('')
      }
      return { role, content }
    }).filter(msg => msg.content)
    
    // Recalculate optimal width
    leftPaneWidth.value = calculateOptimalChatWidth()
    
    await nextTick()
    scrollToBottom()
    alert('Context compressed successfully!')
  } catch (error) {
    console.error('Failed to compress context:', error)
    alert('Failed to compress context: ' + error.message)
  }
}

const handleResetContext = async () => {
  if (!sessionId.value || messages.value.length === 0) return
  
  if (!confirm('Reset all conversation history? This will permanently delete all messages. This action cannot be undone.')) {
    return
  }
  
  try {
    await resetContext(sessionId.value)
    messages.value = []
    toolExecutions.value = []
    selectedTool.value = null
    
    // Reset pane width to default
    leftPaneWidth.value = calculateOptimalChatWidth()
    
    alert('Context reset successfully!')
  } catch (error) {
    console.error('Failed to reset context:', error)
    alert('Failed to reset context: ' + error.message)
  }
}

// Resizable pane handlers
const startDragging = () => {
  isDragging.value = true
  document.addEventListener('mousemove', handleDrag)
  document.addEventListener('mouseup', stopDragging)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

const handleDrag = (e) => {
  if (!isDragging.value) return
  const container = document.querySelector('.split-container')
  if (!container) return
  const containerWidth = container.offsetWidth
  const newWidth = (e.clientX / containerWidth) * 100
  // Constrain between 30% and 80%
  leftPaneWidth.value = Math.max(30, Math.min(80, newWidth))
}

const stopDragging = () => {
  isDragging.value = false
  document.removeEventListener('mousemove', handleDrag)
  document.removeEventListener('mouseup', stopDragging)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// Vertical resizable pane handlers (for right pane top/bottom split)
const startDraggingVertical = () => {
  isDraggingVertical.value = true
  document.addEventListener('mousemove', handleDragVertical)
  document.addEventListener('mouseup', stopDraggingVertical)
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
}

const handleDragVertical = (e) => {
  if (!isDraggingVertical.value) return
  const rightPane = document.querySelector('.right-pane')
  if (!rightPane) return
  const rect = rightPane.getBoundingClientRect()
  const offsetY = e.clientY - rect.top
  const newHeight = (offsetY / rect.height) * 100
  // Constrain between 20% and 80%
  rightTopHeight.value = Math.max(20, Math.min(80, newHeight))
}

const stopDraggingVertical = () => {
  isDraggingVertical.value = false
  document.removeEventListener('mousemove', handleDragVertical)
  document.removeEventListener('mouseup', stopDraggingVertical)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

const handleSelectTool = (tool) => {
  selectedTool.value = tool
}

const sendMessage = async () => {
  if (!inputMessage.value.trim() || isSending.value || !sessionId.value) return

  const userMessage = inputMessage.value.trim()
  inputMessage.value = ''
  isSending.value = true

  // Add user message to UI
  messages.value.push({
    role: 'user',
    content: userMessage,
  })

  // Scroll to bottom
  await nextTick()
  scrollToBottom()

  // Show thinking indicator
  isThinking.value = true
  thinkingMessage.value = 'Agent is thinking...'

  try {
    let agentContent = ''
    let currentToolName = null

    // Stream response
    await apiSendMessage(
      userMessage,
      mode.value,
      async (chunk) => {
        const chunkType = chunk.type

        if (chunkType === 'token') {
          agentContent += chunk.content || ''
          isThinking.value = false
          currentTool.value = null
          currentToolCommand.value = null
          
          // Update or create agent message
          const lastMessage = messages.value[messages.value.length - 1]
          if (lastMessage && lastMessage.role === 'agent' && !currentToolName) {
            lastMessage.content = agentContent
          } else {
            messages.value.push({
              role: 'agent',
              content: agentContent,
            })
          }
          
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'tool_call') {
          currentToolName = chunk.tool_name
          currentTool.value = chunk.tool_name
          
          // Track tool execution
          const toolExecution = {
            name: chunk.tool_name,
            input: chunk.tool_input,
            output: null,
            status: 'pending',
            timestamp: Date.now()
          }
          toolExecutions.value.push(toolExecution)
          
          // Auto-adjust width when first tool is executed to give more space to tools panel
          if (toolExecutions.value.length === 1) {
            leftPaneWidth.value = calculateOptimalChatWidth()
          }
          
          // Extract bash command if it's a bash tool call
          if (chunk.tool_name === 'bash' && chunk.tool_input) {
            try {
              const input = typeof chunk.tool_input === 'string' ? JSON.parse(chunk.tool_input) : chunk.tool_input
              currentToolCommand.value = input.command || null
            } catch (e) {
              currentToolCommand.value = null
            }
          } else {
            currentToolCommand.value = null
          }
          isThinking.value = true
          thinkingMessage.value = `Agent is working...`
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'permission_request') {
          // Handle permission request
          const perm = chunk.permission_request || {}
          const reply = await handlePermissionRequest(perm)
          if (reply) {
            // Permission reply will be handled by API client
          }
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'tool_result') {
          // Update the last tool execution with the result
          if (toolExecutions.value.length > 0) {
            const lastTool = toolExecutions.value[toolExecutions.value.length - 1]
            if (lastTool.status === 'pending') {
              lastTool.output = chunk.tool_output
              lastTool.status = 'completed'
            }
          }
          
          currentToolName = null
          currentTool.value = null
          currentToolCommand.value = null
          isThinking.value = false
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'done') {
          isThinking.value = false
          currentTool.value = null
          currentToolCommand.value = null
          if (agentContent) {
            // Ensure final message is rendered
            const lastMessage = messages.value[messages.value.length - 1]
            if (lastMessage && lastMessage.role === 'agent') {
              lastMessage.content = agentContent
            }
          }
        } else if (chunkType === 'error') {
          isThinking.value = false
          messages.value.push({
            role: 'agent',
            content: `**Error:** ${chunk.content}`,
          })
        }
      }
    )
  } catch (error) {
    console.error('Error sending message:', error)
    isThinking.value = false
    messages.value.push({
      role: 'agent',
      content: `**Error:** ${error.message}`,
    })
  } finally {
    isSending.value = false
    inputRef.value?.focus()
  }
}

const handlePermissionRequest = async (perm) => {
  return new Promise((resolve) => {
    pendingPermission.value = perm
    permissionResolve.value = resolve
  })
}

const handlePermissionReply = async (reply) => {
  const perm = pendingPermission.value
  pendingPermission.value = null
  
  const requestId = perm?.id || perm?.request_id
  if (requestId) {
    try {
      console.log('Sending permission reply:', { requestId, reply })
      await replyToPermission(requestId, reply)
      console.log('Permission reply sent successfully')
    } catch (error) {
      console.error('Failed to send permission reply:', error)
    }
  } else {
    console.error('No request ID found in permission object:', perm)
  }
  
  if (permissionResolve.value) {
    permissionResolve.value(reply)
    permissionResolve.value = null
  }
}

const scrollToBottom = () => {
  const main = document.querySelector('main')
  if (main) {
    main.scrollTop = main.scrollHeight
  }
}

const handleExitSession = () => {
  clearSession()
  currentSession.value = null
  messages.value = []
  toolExecutions.value = []
  selectedTool.value = null
  leftPaneWidth.value = 70 // Reset to default width
  showSessionSelector.value = true
}

const handleSelectSession = async (id) => {
  try {
    const session = await getSession(id)
    setSession(id)
    currentSession.value = session
    showSessionSelector.value = false
    
    // Clear tool executions for new session
    toolExecutions.value = []
    selectedTool.value = null
    
    // Load message history from session
    try {
      const messageHistory = await getSessionMessages(id)
      console.log('Loaded message history:', messageHistory)
      
      // Extract tool executions from message parts
      toolExecutions.value = extractToolExecutions(messageHistory)
      console.log('Extracted tool executions:', toolExecutions.value)
      
      // Convert backend format to frontend format
      // Server returns messages newest first, so reverse to get chronological order
      // [{info: {role: 'user'|'assistant', ...}, parts: [{type: 'text', text: '...'}]}]
      messages.value = messageHistory.reverse().map(msg => {
        const info = msg.info
        const role = info.role === 'user' ? 'user' : 'agent'
        
        // Extract content from parts
        let content = ''
        if (msg.parts && msg.parts.length > 0) {
          // Combine all text parts
          content = msg.parts
            .filter(part => part.type === 'text')
            .map(part => part.text)
            .join('')
        }
        
        return { role, content }
      }).filter(msg => msg.content) // Skip empty messages
      
      console.log('Converted messages:', messages.value)
      
      // Auto-calculate optimal chat pane width
      leftPaneWidth.value = calculateOptimalChatWidth()
    } catch (error) {
      console.error('Failed to load message history:', error)
      messages.value = []
      leftPaneWidth.value = 70
    }
    
    await nextTick()
    scrollToBottom()
  } catch (error) {
    console.error('Failed to select session:', error)
    alert('Failed to load session: ' + error.message)
  }
}

const handleCreateSession = (payload) => {
  const payloadIsObj = payload && typeof payload === 'object' && !Array.isArray(payload)
  const session = payloadIsObj ? payload.session : payload
  const sessionName = payloadIsObj ? payload.sessionName : null
  currentSession.value = { ...session, title: sessionName || (session?.title) }
  showSessionSelector.value = false
  messages.value = []
  toolExecutions.value = []
  selectedTool.value = null
  
  // Auto-calculate optimal chat pane width for new session
  leftPaneWidth.value = calculateOptimalChatWidth()
}

const initializeSession = async () => {
  isInitializing.value = true
  try {
    // Check health
    await health()
    
    // If we have a session ID from localStorage, try to load it
    if (sessionId.value) {
      try {
        const session = await getSession(sessionId.value)
        currentSession.value = session
        
        // Load message history
        try {
          const messageHistory = await getSessionMessages(sessionId.value)
          console.log('Loaded message history on init:', messageHistory)
          
          // Extract tool executions from message parts
          toolExecutions.value = extractToolExecutions(messageHistory)
          console.log('Extracted tool executions on init:', toolExecutions.value)
          
          // Convert backend format to frontend format
          // Server returns messages newest first, so reverse to get chronological order
          messages.value = messageHistory.reverse().map(msg => {
            const info = msg.info
            const role = info.role === 'user' ? 'user' : 'agent'
            
            // Extract content from parts
            let content = ''
            if (msg.parts && msg.parts.length > 0) {
              content = msg.parts
                .filter(part => part.type === 'text')
                .map(part => part.text)
                .join('')
            }
            
            return { role, content }
          }).filter(msg => msg.content)
          
          console.log('Converted messages on init:', messages.value)
          
          // Auto-calculate optimal chat pane width
          leftPaneWidth.value = calculateOptimalChatWidth()
          
          await nextTick()
          scrollToBottom()
        } catch (error) {
          console.error('Failed to load message history:', error)
          messages.value = []
          leftPaneWidth.value = 70
        }
      } catch (error) {
        // Session doesn't exist, clear it and show selector
        console.warn('Stored session not found, clearing:', error)
        clearSession()
        showSessionSelector.value = true
      }
    } else {
      // No session, show selector
      showSessionSelector.value = true
    }
  } catch (error) {
    console.error('Failed to initialize:', error)
    showSessionSelector.value = true
  } finally {
    isInitializing.value = false
  }
}

onMounted(async () => {
  await initializeSession()
  
  // Focus input when ready
  await nextTick()
  if (!showSessionSelector.value) {
    inputRef.value?.focus()
  }
})
</script>
