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
              <!-- Questions Pending Notice -->
              <div v-if="pendingQuestionData" class="bg-accent/20 border border-accent rounded-lg p-3 flex items-center gap-2">
                <svg class="w-5 h-5 text-accent flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span class="text-sm text-text-inverse">The agent has asked {{ pendingQuestionData.questions.length }} question{{ pendingQuestionData.questions.length > 1 ? 's' : '' }}. Please answer in the dialog above.</span>
              </div>
              
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
                  :disabled="!sessionId || pendingQuestionData"
                  class="flex-1 px-4 py-3 bg-accent text-text-inverse rounded-2xl border-none focus:outline-none focus:ring-2 focus:ring-accent-hover resize-none custom-scrollbar disabled:opacity-50 disabled:cursor-not-allowed placeholder-text-inverse/60"
                  rows="5"
                  ref="inputRef"
                ></textarea>
                <button
                  @click="sendMessage"
                  :disabled="!inputMessage.trim() || isSending || !sessionId || pendingQuestionData"
                  class="px-6 py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium transition-colors self-end"
                >
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
          <!-- Top Section - Tool List -->
          <div class="bg-surface/30 border-b border-surface-dark overflow-auto" :style="{ height: rightTopHeight + '%' }">
            <ToolList 
              :tools="toolExecutions" 
              :selectedTool="selectedTool"
              @select="handleSelectTool"
            />
          </div>
          
          <!-- Vertical Draggable Divider -->
          <div 
            @mousedown="startDraggingVertical"
            class="h-1 bg-surface-dark hover:bg-accent cursor-row-resize transition-colors flex-shrink-0"
            :class="{ 'bg-accent': isDraggingVertical }"
          ></div>
          
          <!-- Bottom Section - Tool Output -->
          <div class="flex-1 overflow-hidden" :style="{ height: (100 - rightTopHeight) + '%' }">
            <ToolOutput :tool="selectedTool" />
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

      <!-- Question Dialog -->
      <QuestionDialog
        v-if="pendingQuestionData"
        :questionData="pendingQuestionData"
        @submit="handleQuestionSubmit"
        @skip="handleQuestionSkip"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useApiClient } from './composables/useApiClient'
import SessionSelector from './components/SessionSelector.vue'
import PermissionDialog from './components/PermissionDialog.vue'
import QuestionDialog from './components/QuestionDialog.vue'
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
const pendingQuestionData = ref(null)

// Session state tracking - persisted across reloads
// States: 'idle' | 'thinking' | 'working' | 'waiting_permission' | 'executing_tool'
const sessionState = ref('idle')

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

// State persistence helpers
const saveSessionState = () => {
  if (!sessionId.value) return
  
  const state = {
    sessionState: sessionState.value,
    isThinking: isThinking.value,
    thinkingMessage: thinkingMessage.value,
    currentTool: currentTool.value,
    currentToolCommand: currentToolCommand.value,
    pendingQuestionData: pendingQuestionData.value,
    timestamp: Date.now()
  }
  
  try {
    const key = `openscrum_state_${sessionId.value}`
    localStorage.setItem(key, JSON.stringify(state))
    console.log('[State] Saved session state to', key)
    console.log('[State] pendingQuestionData saved?', !!state.pendingQuestionData)
    if (state.pendingQuestionData) {
      console.log('[State] Question data keys:', Object.keys(state.pendingQuestionData))
    }
  } catch (error) {
    console.error('[State] Failed to save state:', error)
  }
}

const restoreSessionState = () => {
  if (!sessionId.value) return
  
  try {
    const key = `openscrum_state_${sessionId.value}`
    const saved = localStorage.getItem(key)
    console.log('[State] Attempting to restore from', key)
    console.log('[State] localStorage value exists?', !!saved)
    
    if (saved) {
      const state = JSON.parse(saved)
      
      // Only restore if timestamp is recent (within 1 hour)
      const age = Date.now() - (state.timestamp || 0)
      console.log('[State] Saved state age (ms):', age, 'max:', 3600000)
      
      if (age < 3600000) {
        sessionState.value = state.sessionState || 'idle'
        isThinking.value = state.isThinking || false
        thinkingMessage.value = state.thinkingMessage || 'Thinking...'
        currentTool.value = state.currentTool || null
        currentToolCommand.value = state.currentToolCommand || null
        pendingQuestionData.value = state.pendingQuestionData || null
        console.log('[State] Restored session state')
        console.log('[State] pendingQuestionData restored?', !!pendingQuestionData.value)
        if (pendingQuestionData.value) {
          console.log('[State] Restored question data:', pendingQuestionData.value)
        } else {
          console.log('[State] No pendingQuestionData in saved state')
        }
      } else {
        console.log('[State] Saved state too old, starting fresh')
        clearSessionState()
      }
    } else {
      console.log('[State] No saved state found in localStorage')
    }
  } catch (error) {
    console.error('[State] Failed to restore state:', error)
  }
}

const clearSessionState = () => {
  if (!sessionId.value) return
  
  try {
    localStorage.removeItem(`openscrum_state_${sessionId.value}`)
    sessionState.value = 'idle'
    isThinking.value = false
    thinkingMessage.value = 'Thinking...'
    currentTool.value = null
    currentToolCommand.value = null
    pendingQuestionData.value = null
    console.log('[State] Cleared session state')
  } catch (error) {
    console.error('[State] Failed to clear state:', error)
  }
}

const updateSessionState = (newState, thinking = false, message = 'Thinking...', tool = null, command = null) => {
  sessionState.value = newState
  isThinking.value = thinking
  thinkingMessage.value = message
  currentTool.value = tool
  currentToolCommand.value = command
  saveSessionState()
  console.log('[State] Updated to:', newState, 'thinking:', thinking)
}

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

// Helper to detect structured JSON questions in agent's message
const detectStructuredQuestions = (content) => {
  console.log('[Questions] detectStructuredQuestions called, content type:', typeof content, 'length:', content?.length)
  
  if (!content || typeof content !== 'string') {
    console.log('[Questions] Content is not a string, returning null')
    return null
  }
  
  // Try to parse as JSON
  const trimmed = content.trim()
  console.log('[Questions] Trimmed content starts with {?', trimmed.startsWith('{'), 'ends with }?', trimmed.endsWith('}'))
  
  if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) {
    console.log('[Questions] Content is not JSON-like, returning null')
    return null
  }
  
  try {
    console.log('[Questions] Attempting to parse JSON...')
    const parsed = JSON.parse(trimmed)
    console.log('[Questions] Successfully parsed JSON, keys:', Object.keys(parsed))
    
    // Check if it has the questions structure directly
    if (parsed.type === 'questions' && Array.isArray(parsed.questions) && parsed.questions.length > 0) {
      console.log('[Questions] ✓ Detected structured questions (direct format):', parsed)
      return parsed
    }
    
    // Check if questions are nested under a 'questions' property
    if (parsed.questions && typeof parsed.questions === 'object') {
      console.log('[Questions] Found nested questions property, checking structure...')
      const questionsData = parsed.questions
      console.log('[Questions] questionsData type:', questionsData.type, 'has questions array?', Array.isArray(questionsData.questions))
      
      if (questionsData.type === 'questions' && Array.isArray(questionsData.questions) && questionsData.questions.length > 0) {
        console.log('[Questions] ✓ Detected structured questions (nested format):', questionsData)
        return questionsData
      } else {
        console.log('[Questions] Nested questions object does not match expected structure')
      }
    } else {
      console.log('[Questions] No questions property found or it is not an object')
    }
  } catch (e) {
    // Not valid JSON or not questions structure
    console.log('[Questions] Failed to parse JSON:', e.message)
  }
  
  console.log('[Questions] No questions detected, returning null')
  return null
}

const handleQuestionSubmit = async (answersObj) => {
  pendingQuestionData.value = null
  
  // Format answers as JSON string for the agent
  const answersText = 'Here are my answers:\n```json\n' + JSON.stringify(answersObj, null, 2) + '\n```'
  
  // Send the answers as a new user message
  inputMessage.value = answersText
  await sendMessage()
}

const handleQuestionSkip = () => {
  pendingQuestionData.value = null
  // Don't send anything, just close the dialog
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
    
    // Check if the last message contains questions
    if (messages.value.length > 0) {
      const lastMessage = messages.value[messages.value.length - 1]
      if (lastMessage && lastMessage.role === 'agent') {
        console.log('[Questions] Checking last message after compress for questions...')
        const questionData = detectStructuredQuestions(lastMessage.content)
        if (questionData) {
          console.log('[Questions] ✓ Found questions in last message after compress')
          pendingQuestionData.value = questionData
          
          // Update the message content to show only the text part
          try {
            const parsed = JSON.parse(lastMessage.content.trim())
            if (parsed.content && typeof parsed.content === 'string') {
              lastMessage.content = parsed.content
            }
          } catch (e) {
            // Keep original if parsing fails
          }
        }
      }
    }
    
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
  
  if (!confirm('Reset all conversation history? This will permanently delete all messages and clear all state. This action cannot be undone.')) {
    return
  }
  
  try {
    await resetContext(sessionId.value)
    messages.value = []
    toolExecutions.value = []
    selectedTool.value = null
    pendingQuestionData.value = null
    
    // Clear session state (thinking indicator, etc.)
    clearSessionState()
    
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
  updateSessionState('thinking', true, 'Agent is thinking...')

  try {
    let agentContent = ''
    let currentToolName = null

    // Stream response
    await apiSendMessage(
      userMessage,
      mode.value,
      async (chunk) => {
        const chunkType = chunk.type
        console.log('[Stream] Chunk type:', chunkType, 'isThinking:', isThinking.value)

        if (chunkType === 'token') {
          agentContent += chunk.content || ''
          updateSessionState('idle', false)
          console.log('[Stream] Token received, state set to idle')
          
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
          console.log('[Stream] Tool call:', chunk.tool_name, 'setting state to working')
          
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
              const cmd = input.command || null
              updateSessionState('executing_tool', true, 'Agent is working...', chunk.tool_name, cmd)
            } catch (e) {
              updateSessionState('executing_tool', true, 'Agent is working...', chunk.tool_name)
            }
          } else {
            updateSessionState('executing_tool', true, 'Agent is working...', chunk.tool_name)
          }
          console.log('[Stream] Tool call UI updated, state:', sessionState.value)
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'permission_request') {
          // Handle permission request
          const perm = chunk.permission_request || {}
          console.log('[Stream] Permission request, showing dialog')
          // Update state to waiting for permission
          updateSessionState('waiting_permission', true, 'Permission required...', perm.tool || null)
          await nextTick()
          scrollToBottom()
          
          console.log('[Stream] Waiting for permission reply...')
          const reply = await handlePermissionRequest(perm)
          console.log('[Stream] Got permission reply:', reply)
          
          // After user responds, update state accordingly
          if (reply && reply.decision === 'approved') {
            updateSessionState('executing_tool', true, 'Tool executing...', perm.tool || null)
            console.log('[Stream] Permission approved, state:', sessionState.value)
          } else if (reply && reply.decision === 'rejected') {
            updateSessionState('thinking', true, 'Permission denied, continuing...')
            console.log('[Stream] Permission rejected, state:', sessionState.value)
          }
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'tool_result') {
          console.log('[Stream] Tool result received')
          // Update the last tool execution with the result
          if (toolExecutions.value.length > 0) {
            const lastTool = toolExecutions.value[toolExecutions.value.length - 1]
            if (lastTool.status === 'pending') {
              lastTool.output = chunk.tool_output
              lastTool.status = 'completed'
            }
          }
          
          // Update state - LLM is now processing the tool result
          updateSessionState('thinking', true, 'Agent is thinking...')
          console.log('[Stream] Tool result processed, waiting for LLM response')
          await nextTick()
          scrollToBottom()
        } else if (chunkType === 'done') {
          // Use content from done chunk if available (contains complete final response)
          const finalContent = chunk.content || agentContent
          console.log('[Stream] Done chunk received')
          console.log('[Stream] Done chunk content length:', chunk.content?.length || 0)
          console.log('[Stream] Accumulated agentContent length:', agentContent?.length || 0)
          console.log('[Stream] Using content, first 200 chars:', finalContent?.substring(0, 200))
          
          updateSessionState('idle', false)
          currentTool.value = null
          currentToolCommand.value = null
          
          if (finalContent) {
            // Check if the agent returned structured questions
            console.log('[Questions] Checking for questions in final content...')
            const questionData = detectStructuredQuestions(finalContent)
            console.log('[Questions] Detection result:', questionData ? 'FOUND' : 'NOT FOUND')
            
            // If we found questions, extract the content separately
            let displayContent = finalContent
            if (questionData) {
              try {
                const parsed = JSON.parse(finalContent.trim())
                // If there's a separate content field, use that for display
                if (parsed.content && typeof parsed.content === 'string') {
                  displayContent = parsed.content
                  console.log('[Questions] Extracted display content, length:', displayContent.length)
                }
              } catch (e) {
                // Keep original content if parsing fails
                console.log('[Questions] Failed to extract content:', e.message)
              }
              console.log('[Questions] Setting pendingQuestionData.value')
              pendingQuestionData.value = questionData
              console.log('[Questions] pendingQuestionData.value is now:', !!pendingQuestionData.value)
            }
            
            // Ensure final message is rendered with the display content
            const lastMessage = messages.value[messages.value.length - 1]
            if (lastMessage && lastMessage.role === 'agent') {
              lastMessage.content = displayContent
            }
          }
        } else if (chunkType === 'error') {
          updateSessionState('idle', false)
          messages.value.push({
            role: 'agent',
            content: `**Error:** ${chunk.content}`,
          })
        }
      }
    )
  } catch (error) {
    console.error('Error sending message:', error)
    updateSessionState('idle', false)
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
  
  // Note: isThinking state is managed by the permission_request handler
  // after this reply is returned
}

const scrollToBottom = (smooth = false) => {
  // Use requestAnimationFrame to ensure DOM is fully updated
  requestAnimationFrame(() => {
    const main = document.querySelector('main')
    if (main) {
      if (smooth) {
        main.scrollTo({
          top: main.scrollHeight,
          behavior: 'smooth'
        })
      } else {
        main.scrollTop = main.scrollHeight
      }
    }
  })
}

const handleExitSession = () => {
  clearSession()
  clearSessionState()
  currentSession.value = null
  messages.value = []
  toolExecutions.value = []
  selectedTool.value = null
  pendingQuestionData.value = null
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
      
      // Restore session state (thinking indicator, etc.) - DO THIS FIRST
      restoreSessionState()
      
      // Check if the last message contains questions (if not already restored from state)
      if (!pendingQuestionData.value && messages.value.length > 0) {
        const lastMessage = messages.value[messages.value.length - 1]
        if (lastMessage && lastMessage.role === 'agent') {
          console.log('[Questions] Checking last message on session select for questions...')
          const questionData = detectStructuredQuestions(lastMessage.content)
          if (questionData) {
            console.log('[Questions] ✓ Found questions in last message on session select')
            pendingQuestionData.value = questionData
            
            // Update the message content to show only the text part
            try {
              const parsed = JSON.parse(lastMessage.content.trim())
              if (parsed.content && typeof parsed.content === 'string') {
                lastMessage.content = parsed.content
                console.log('[Questions] Extracted display content from nested JSON')
              }
            } catch (e) {
              // Keep original if parsing fails
            }
          }
        }
      }
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
  pendingQuestionData.value = null
  
  // Clear state for new session
  clearSessionState()
  
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
          
          // Restore session state (thinking indicator, etc.) - DO THIS FIRST
          restoreSessionState()
          
          // Check if the last message contains questions (if not already restored from state)
          if (!pendingQuestionData.value && messages.value.length > 0) {
            const lastMessage = messages.value[messages.value.length - 1]
            if (lastMessage && lastMessage.role === 'agent') {
              console.log('[Questions] Checking last message on init for questions...')
              const questionData = detectStructuredQuestions(lastMessage.content)
              if (questionData) {
                console.log('[Questions] ✓ Found questions in last message on init')
                pendingQuestionData.value = questionData
                
                // Update the message content to show only the text part
                try {
                  const parsed = JSON.parse(lastMessage.content.trim())
                  if (parsed.content && typeof parsed.content === 'string') {
                    lastMessage.content = parsed.content
                    console.log('[Questions] Extracted display content from nested JSON')
                  }
                } catch (e) {
                  // Keep original if parsing fails
                }
              }
            }
          }
          
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

// Watch for permission dialog closing to auto-scroll
watch(pendingPermission, async (newVal, oldVal) => {
  if (oldVal && !newVal) {
    await nextTick()
    scrollToBottom()
  }
})

// Watch for when we finish sending (transition to waiting for user input)
// and check if the last LLM response contains questions
watch(isSending, async (newVal, oldVal) => {
  console.log('[Questions] isSending watch triggered, oldVal:', oldVal, 'newVal:', newVal)
  // When we transition from sending to idle (waiting for user input)
  if (oldVal && !newVal && messages.value.length > 0) {
    console.log('[Questions] Transitioned from sending to idle, checking last message...')
    const lastMessage = messages.value[messages.value.length - 1]
    
    // Only check agent messages
    if (lastMessage && lastMessage.role === 'agent') {
      console.log('[Questions] Last message is from agent, content length:', lastMessage.content?.length)
      const questionData = detectStructuredQuestions(lastMessage.content)
      if (questionData && !pendingQuestionData.value) {
        console.log('[Questions] ✓ Detected questions in last message after send complete (fallback detection)')
        pendingQuestionData.value = questionData
        
        // Also update the message content to remove the questions JSON
        try {
          const parsed = JSON.parse(lastMessage.content.trim())
          if (parsed.content && typeof parsed.content === 'string') {
            console.log('[Questions] Extracting content from nested JSON')
            lastMessage.content = parsed.content
          }
        } catch (e) {
          // Keep original if parsing fails
          console.log('[Questions] Could not extract content:', e.message)
        }
      } else if (questionData) {
        console.log('[Questions] Questions already set, skipping duplicate')
      } else {
        console.log('[Questions] No questions found in last message')
      }
    } else {
      console.log('[Questions] Last message is not from agent or no messages')
    }
  }
})

// Watch for question data changes to persist state
watch(pendingQuestionData, (newVal, oldVal) => {
  console.log('[Questions] pendingQuestionData changed from', !!oldVal, 'to', !!newVal)
  if (newVal) {
    console.log('[Questions] Question data:', JSON.stringify(newVal, null, 2))
  }
  saveSessionState()
})

onMounted(async () => {
  await initializeSession()
  
  // Focus input when ready
  await nextTick()
  if (!showSessionSelector.value) {
    inputRef.value?.focus()
  }
})
</script>
