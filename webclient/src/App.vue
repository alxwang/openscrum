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
            <button
              @click="handleResetSession"
              :disabled="!sessionId"
              class="px-3 py-1.5 text-sm rounded-lg bg-red-700 hover:bg-red-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Reset entire session - deletes all messages AND workspace files (cannot be undone)"
            >
              Reset Session
            </button>
          </div>
        </div>
      </header>

      <!-- Split View Container - 3 Panes -->
      <div v-if="!isInitializing && !showSessionSelector" class="flex-1 flex overflow-hidden split-container">
        <!-- Left Pane - Chat (40%) -->
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
                v-for="(message, index) in displayMessages"
                :key="index"
                class="flex justify-start"
              >
                <div 
                  v-if="message.hasContent"
                  :class="[
                    'max-w-[85%]',
                    message.role === 'user' ? 'message-user' : 'message-agent',
                    'cursor-pointer hover:opacity-90 transition-opacity'
                  ]"
                  @dblclick="copyMessageToClipboard(message, index, $event)"
                  title="Double-click to copy"
                >
                  <div v-if="message.role === 'agent'" class="prose prose-invert max-w-none">
                    <div v-html="marked.parse(formatMessageContent(message.displayContent))"></div>
                  </div>
                  <div v-else class="whitespace-pre-wrap">{{ message.displayContent }}</div>
                </div>
              </div>
              
              <!-- Copied indicator at cursor position -->
              <div 
                v-if="copiedMessageIndex !== null"
                class="fixed bg-green-600 text-white text-xs px-3 py-1 rounded-full shadow-lg z-50 pointer-events-none animate-fade-in"
                :style="{ 
                  left: copiedMessagePosition.x + 'px', 
                  top: (copiedMessagePosition.y - 30) + 'px',
                  transform: 'translateX(-50%)'
                }"
              >
                ✓ Copied!
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
                <div class="flex flex-col gap-2">
                  <!-- Token Usage Indicator -->
                  <TokenUsageIndicator 
                    v-if="sessionId"
                    :tokenCount="tokenUsage.tokenCount"
                    :tokenLimit="tokenUsage.tokenLimit"
                    :shouldCompress="tokenUsage.shouldCompress"
                    :show="tokenUsage.tokenCount > 0"
                  />
                  <button
                    @click="sendMessage"
                    :disabled="!inputMessage.trim() || isSending || !sessionId || pendingQuestionData"
                    class="px-6 py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium transition-colors"
                  >
                    Send
                  </button>
                </div>
              </div>
            </div>
          </footer>
        </div>

        <!-- Left Draggable Divider (between left and center) -->
        <div 
          @mousedown="startDraggingLeft"
          class="w-1 bg-surface-dark hover:bg-accent cursor-col-resize transition-colors flex-shrink-0"
          :class="{ 'bg-accent': isDraggingLeft }"
        ></div>

        <!-- Center Pane - Progress/Plan Display or Design Docs (30%) -->
        <div class="flex flex-col bg-surface/50 border-r border-surface-dark" :style="{ width: centerPaneWidth + '%' }">
          <!-- Plan Mode: Design Document List -->
          <div v-if="mode === 'plan'" class="h-full">
            <DesignDocList
              :documents="designDocuments"
              :selectedDoc="selectedDesignDoc"
              @select="handleSelectDesignDoc"
            />
          </div>
          
          <!-- Edit Mode: Progress Tracker -->
          <div v-else-if="latestProgress && mode === 'edit'" class="p-4 overflow-y-auto custom-scrollbar">
            <ProgressTracker 
              :plan="latestProgress.plan"
              :currentProgress="latestProgress.current_progress"
            />
          </div>
          
          <!-- Empty State / Mode Info -->
          <div v-else class="flex items-center justify-center h-full text-text-muted px-4">
            <div class="text-center">
              <p class="text-sm">
                Progress will appear here during execution
              </p>
            </div>
          </div>
        </div>

        <!-- Right Draggable Divider (between center and right) -->
        <div 
          @mousedown="startDraggingRight"
          class="w-1 bg-surface-dark hover:bg-accent cursor-col-resize transition-colors flex-shrink-0"
          :class="{ 'bg-accent': isDraggingRight }"
        ></div>

        <!-- Right Pane - Tools or Design Doc Viewer (30%) -->
        <div class="flex flex-col bg-surface/30 right-pane" :style="{ width: (100 - leftPaneWidth - centerPaneWidth) + '%' }">
          <!-- Plan Mode: Design Document Viewer -->
          <div v-if="mode === 'plan'" class="h-full">
            <DesignDocViewer
              :docType="selectedDesignDoc"
              :docInfo="designDocInfo"
              :content="selectedDesignDocContent"
              @save="handleSaveDesignDoc"
            />
          </div>
          
          <!-- Edit Mode: Tool List and Output (Split view) -->
          <template v-else>
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
          </template>
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
import TokenUsageIndicator from './components/TokenUsageIndicator.vue'
import ToolList from './components/ToolList.vue'
import ToolOutput from './components/ToolOutput.vue'
import DesignDocList from './components/DesignDocList.vue'
import DesignDocViewer from './components/DesignDocViewer.vue'
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
  resetSession,
  getTokenUsage,
  sessionId,
  modelName 
} = useApiClient()

const mode = ref('plan')
const inputMessage = ref('')
const messages = ref([])

// Computed property for displaying messages (avoid calling extractDisplayContent multiple times)
const displayMessages = computed(() => {
  console.log('[DisplayMessages] Computing display messages, count:', messages.value.length)
  return messages.value.map((msg, index) => {
    if (msg.role === 'agent') {
      console.log(`[DisplayMessages] Processing agent message ${index}, content length:`, msg.content?.length, 'starts with:', msg.content?.substring(0, 50))
      const displayContent = extractDisplayContent(msg.content)
      console.log(`[DisplayMessages] Message ${index} display content length:`, displayContent?.length, 'has content:', !!displayContent && displayContent.trim() !== '')
      return {
        ...msg,
        displayContent: displayContent || '', // Store processed content
        hasContent: !!displayContent && displayContent.trim() !== ''
      }
    }
    return {
      ...msg,
      displayContent: msg.content,
      hasContent: true
    }
  })
})

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

// Design documents state (Plan Mode)
const designDocuments = ref({})
const selectedDesignDoc = ref(null)
const selectedDesignDocContent = ref(null)
const designDocInfo = ref(null)
const autoSaveTimer = ref(null)

// Session state tracking - persisted across reloads
// States: 'idle' | 'thinking' | 'working' | 'waiting_permission' | 'executing_tool'
const sessionState = ref('idle')

// Latest progress/plan data (displayed in center pane)
const latestProgress = ref(null)

// Resizable panes state (3-pane layout)
const leftPaneWidth = ref(40) // Left pane (chat) - 40%
const centerPaneWidth = ref(30) // Center pane (empty for now) - 30%
const isDraggingLeft = ref(false) // Dragging between left and center
const isDraggingRight = ref(false) // Dragging between center and right
const rightTopHeight = ref(33.33) // 1/3 of right pane height in percentage
const isDraggingVertical = ref(false)

// Tool execution tracking
const toolExecutions = ref([])
const selectedTool = ref(null)

// Token usage tracking
const tokenUsage = ref({
  tokenCount: 0,
  tokenLimit: 128000,
  usagePercentage: 0,
  shouldCompress: false,
  model: '',
  messageCount: 0,
})

// Copy to clipboard tracking
const copiedMessageIndex = ref(null)
const copiedMessagePosition = ref({ x: 0, y: 0 })

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
    latestProgress.value = null
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
  // For 3-pane layout, return default of 40% for left pane
  // Center pane is always 30%, right pane gets the remaining 30%
  return 40
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
  
  // First, try if the entire content is a progress JSON
  const trimmed = content.trim()
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed)
      // Check if it has the progress structure
      if (parsed.plan && parsed.current_progress) {
        return parsed
      }
    } catch (e) {
      // Not valid JSON, continue to check for embedded JSON
    }
  }
  
  // If entire content is not progress JSON, look for embedded JSON blocks
  // Use a more robust approach: find all opening braces and try to parse from there
  const lines = content.split('\n')
  
  // Look for potential JSON start positions (lines with just '{' or starting with '{')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim()
    if (line.startsWith('{')) {
      // Found a potential JSON start, extract from here to end
      const jsonCandidate = lines.slice(i).join('\n')
      
      // Try to find the complete JSON object using brace counting
      let braceCount = 0
      let jsonEnd = -1
      let inString = false
      let escapeNext = false
      
      for (let j = 0; j < jsonCandidate.length; j++) {
        const char = jsonCandidate[j]
        
        if (escapeNext) {
          escapeNext = false
          continue
        }
        
        if (char === '\\') {
          escapeNext = true
          continue
        }
        
        if (char === '"') {
          inString = !inString
          continue
        }
        
        if (!inString) {
          if (char === '{') {
            braceCount++
          } else if (char === '}') {
            braceCount--
            if (braceCount === 0) {
              jsonEnd = j + 1
              break
            }
          }
        }
      }
      
      if (jsonEnd > 0) {
        const jsonStr = jsonCandidate.substring(0, jsonEnd)
        try {
          const parsed = JSON.parse(jsonStr)
          // Check if it has the progress structure
          if (parsed.plan && parsed.current_progress) {
            return parsed
          }
        } catch (e) {
          // Not valid JSON, continue to next potential start
          continue
        }
      }
    }
  }
  
  return null
}

// Helper to extract displayable content from a message
// Returns null for progress data (shown in ProgressTracker)
// Returns text content for questions data (questions shown in popup)
// Returns original content otherwise
const extractDisplayContent = (content) => {
  if (!content) return ''
  
  // FIRST: Check if it's questions data (higher priority)
  // Try to parse as JSON if it looks like JSON
  const trimmed = content.trim()
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed = JSON.parse(trimmed)
      console.log('[Display] Successfully parsed JSON, keys:', Object.keys(parsed).join(', '))
      
      // IMPORTANT: Remove any tool_calls field if present (should not be in content JSON)
      if (parsed.tool_calls) {
        console.warn('[Display] WARNING: Found tool_calls in content JSON (should not be there), ignoring')
        delete parsed.tool_calls
      }
      
      // Check for questions structure (nested format with content field)
      // This is the format from plan mode: {"content": "...", "questions": {...}}
      if (parsed.questions && typeof parsed.questions === 'object') {
        const questionsData = parsed.questions
        if (questionsData.type === 'questions' && Array.isArray(questionsData.questions)) {
          // This is questions JSON! Return the content field for display
          console.log('[Display] Detected questions JSON (nested format), extracting content field')
          // Unescape newlines in content for proper display
          const contentText = parsed.content || ''
          return contentText.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
        }
      }
      
      // Also check for direct questions format (backward compatibility)
      // Format: {"type": "questions", "questions": [...]}
      if (parsed.type === 'questions' && Array.isArray(parsed.questions)) {
        console.log('[Display] Detected questions JSON (direct format), no content field')
        return '' // No content to display, only questions
      }
      
      // Check for progress structure
      // Progress JSON from edit mode: {"content": "...", "plan": {...}, "current_progress": {...}}
      if (parsed.plan && parsed.current_progress) {
        console.log('[Display] Detected progress JSON')
        // If there's a content field with meaningful text, return it for chat display
        // Progress tracker will show the plan/progress in center pane
        if (parsed.content && typeof parsed.content === 'string' && parsed.content.trim()) {
          console.log('[Display] Progress JSON has content field, extracting for display')
          return parsed.content.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
        }
        // Otherwise don't display anything in chat (progress only in center pane)
        console.log('[Display] Progress JSON without content, returning null')
        return null
      }
      
      // If we got here, it's valid JSON but not a known structure
      // Try to extract a content field if one exists
      if (parsed.content && typeof parsed.content === 'string') {
        console.log('[Display] Unknown JSON structure with content field, extracting content')
        return parsed.content.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
      }
      
      // If no content field, it's JSON we don't want to display
      console.log('[Display] JSON without content field, hiding from display. Keys:', Object.keys(parsed).join(', '))
      return ''
    } catch (e) {
      console.error('[Display] JSON parse failed:', e.message, 'First 200 chars:', trimmed.substring(0, 200))
      
      // Try to extract JSON using brace counting (handle malformed/truncated JSON)
      try {
        let braceCount = 0
        let inString = false
        let escapeNext = false
        let jsonEnd = -1
        
        for (let i = 0; i < trimmed.length; i++) {
          const char = trimmed[i]
          
          if (escapeNext) {
            escapeNext = false
            continue
          }
          
          if (char === '\\') {
            escapeNext = true
            continue
          }
          
          if (char === '"') {
            inString = !inString
            continue
          }
          
          if (!inString) {
            if (char === '{') {
              braceCount++
            } else if (char === '}') {
              braceCount--
              if (braceCount === 0) {
                jsonEnd = i + 1
                break
              }
            }
          }
        }
        
        if (jsonEnd > 0) {
          const validJson = trimmed.substring(0, jsonEnd)
          console.log('[Display] Extracted valid JSON portion, length:', validJson.length)
          const parsed = JSON.parse(validJson)
          
          // Remove tool_calls if present
          if (parsed.tool_calls) {
            console.warn('[Display] Found and removed tool_calls from extracted JSON')
            delete parsed.tool_calls
          }
          
          // Try to extract content field
          if (parsed.content && typeof parsed.content === 'string') {
            console.log('[Display] Extracted content field from repaired JSON')
            return parsed.content.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
          }
          
          // Check for questions
          if (parsed.questions && typeof parsed.questions === 'object') {
            const questionsData = parsed.questions
            if (questionsData.type === 'questions' && Array.isArray(questionsData.questions)) {
              console.log('[Display] Found questions in repaired JSON, extracting content')
              const contentText = parsed.content || ''
              return contentText.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
            }
          }
          
          console.log('[Display] Repaired JSON has no content field, hiding')
          return ''
        }
      } catch (e2) {
        console.error('[Display] Failed to repair JSON:', e2.message)
      }
      
      // If all parsing attempts fail, return as-is
      // (might be text that happens to have { and } characters)
      return content
    }
  }
  
  // Check if it's progress data embedded in text
  const progressData = extractProgressData(content)
  if (progressData) {
    // If progress JSON is embedded, find and remove it, return the remaining text
    const lines = content.split('\n')
    
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim()
      if (line.startsWith('{')) {
        const jsonCandidate = lines.slice(i).join('\n')
        
        // Find the complete JSON object using brace counting
        let braceCount = 0
        let jsonEnd = -1
        let inString = false
        let escapeNext = false
        
        for (let j = 0; j < jsonCandidate.length; j++) {
          const char = jsonCandidate[j]
          
          if (escapeNext) {
            escapeNext = false
            continue
          }
          
          if (char === '\\') {
            escapeNext = true
            continue
          }
          
          if (char === '"') {
            inString = !inString
            continue
          }
          
          if (!inString) {
            if (char === '{') {
              braceCount++
            } else if (char === '}') {
              braceCount--
              if (braceCount === 0) {
                jsonEnd = j + 1
                break
              }
            }
          }
        }
        
        if (jsonEnd > 0) {
          const jsonStr = jsonCandidate.substring(0, jsonEnd)
          try {
            const parsed = JSON.parse(jsonStr)
            if (parsed.plan && parsed.current_progress) {
              // Found the progress JSON, remove it and return the text before it
              const textLines = lines.slice(0, i)
              const textContent = textLines.join('\n').trim()
              return textContent || null
            }
          } catch (e) {
            continue
          }
        }
      }
    }
    
    return null
  }
  
  // Check if it's questions data embedded in text
  const questionData = detectStructuredQuestions(content)
  if (questionData) {
    // Questions found - extract content field from JSON
    try {
      // Try to parse the trimmed content
      const trimmed = content.trim()
      if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
        const parsed = JSON.parse(trimmed)
        // Return the content field if it exists
        if (parsed.content) {
          console.log('[Display] Extracted content field from questions JSON')
          return parsed.content
        }
      }
    } catch (e) {
      console.log('[Display] Failed to extract content from questions JSON:', e.message)
    }
    
    // If embedded in text, find and remove questions JSON, return remaining text
    const lines = content.split('\n')
    
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim()
      if (line.startsWith('{')) {
        const jsonCandidate = lines.slice(i).join('\n')
        
        // Find the complete JSON object using brace counting
        let braceCount = 0
        let jsonEnd = -1
        let inString = false
        let escapeNext = false
        
        for (let j = 0; j < jsonCandidate.length; j++) {
          const char = jsonCandidate[j]
          
          if (escapeNext) {
            escapeNext = false
            continue
          }
          
          if (char === '\\') {
            escapeNext = true
            continue
          }
          
          if (char === '"') {
            inString = !inString
            continue
          }
          
          if (!inString) {
            if (char === '{') {
              braceCount++
            } else if (char === '}') {
              braceCount--
              if (braceCount === 0) {
                jsonEnd = j + 1
                break
              }
            }
          }
        }
        
        if (jsonEnd > 0) {
          const jsonStr = jsonCandidate.substring(0, jsonEnd)
          try {
            const parsed = JSON.parse(jsonStr)
            // Check if this is questions JSON
            const isQuestions = (parsed.type === 'questions' && Array.isArray(parsed.questions)) ||
                               (parsed.questions?.type === 'questions' && Array.isArray(parsed.questions?.questions))
            
            if (isQuestions) {
              // Found the questions JSON, remove it and return the text before it
              const textLines = lines.slice(0, i)
              const textContent = textLines.join('\n').trim()
              return textContent || ''
            }
          } catch (e) {
            continue
          }
        }
      }
    }
    
    return ''
  }
  
  // Regular content - return as-is
  return content
}

// Helper to format message content - wrap JSON in code blocks
const formatMessageContent = (content) => {
  if (!content) return ''
  
  // Check if it's progress JSON - don't format it, we'll show it as a component
  if (extractProgressData(content)) {
    return '' // Return empty string, we'll handle it separately
  }
  
  // NOTE: All JSON structures should already be handled by extractDisplayContent.
  // If we see JSON here, just return it as-is (don't hide it, don't format it)
  // extractDisplayContent should have already decided what to show
  
  return content
}

// Helper to detect structured JSON questions in agent's message
const detectStructuredQuestions = (content) => {
  console.log('[Questions] detectStructuredQuestions called, content type:', typeof content, 'length:', content?.length)
  
  if (!content || typeof content !== 'string') {
    console.log('[Questions] Content is not a string, returning null')
    return null
  }
  
  // First, try if the entire content is a questions JSON
  const trimmed = content.trim()
  console.log('[Questions] Trimmed content starts with {?', trimmed.startsWith('{'), 'ends with }?', trimmed.endsWith('}'))
  
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      console.log('[Questions] Attempting to parse entire content as JSON...')
      const parsed = JSON.parse(trimmed)
      console.log('[Questions] Successfully parsed JSON, keys:', Object.keys(parsed))
      
      // IMPORTANT: Remove any tool_calls field if present (should not be in content JSON)
      if (parsed.tool_calls) {
        console.warn('[Questions] WARNING: Found tool_calls in content JSON (should not be there), ignoring')
        delete parsed.tool_calls
      }
      
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
        }
      }
    } catch (e) {
      console.error('[Questions] Failed to parse entire content as JSON:', e.message, 'First 200 chars:', trimmed.substring(0, 200))
      // Continue to check for embedded JSON
    }
  }
  
  // If entire content is not questions JSON, look for embedded JSON blocks
  console.log('[Questions] Looking for embedded questions JSON...')
  const lines = content.split('\n')
  
  // Look for potential JSON start positions (lines with just '{' or starting with '{')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim()
    if (line.startsWith('{')) {
      // Found a potential JSON start, extract from here to end
      const jsonCandidate = lines.slice(i).join('\n')
      
      // Try to find the complete JSON object using brace counting
      let braceCount = 0
      let jsonEnd = -1
      let inString = false
      let escapeNext = false
      
      for (let j = 0; j < jsonCandidate.length; j++) {
        const char = jsonCandidate[j]
        
        if (escapeNext) {
          escapeNext = false
          continue
        }
        
        if (char === '\\') {
          escapeNext = true
          continue
        }
        
        if (char === '"') {
          inString = !inString
          continue
        }
        
        if (!inString) {
          if (char === '{') {
            braceCount++
          } else if (char === '}') {
            braceCount--
            if (braceCount === 0) {
              jsonEnd = j + 1
              break
            }
          }
        }
      }
      
      if (jsonEnd > 0) {
        const jsonStr = jsonCandidate.substring(0, jsonEnd)
        try {
          const parsed = JSON.parse(jsonStr)
          
          // Check if it has the questions structure directly
          if (parsed.type === 'questions' && Array.isArray(parsed.questions) && parsed.questions.length > 0) {
            console.log('[Questions] ✓ Detected embedded structured questions (direct format)')
            return parsed
          }
          
          // Check if questions are nested
          if (parsed.questions && typeof parsed.questions === 'object') {
            const questionsData = parsed.questions
            if (questionsData.type === 'questions' && Array.isArray(questionsData.questions) && questionsData.questions.length > 0) {
              console.log('[Questions] ✓ Detected embedded structured questions (nested format)')
              return questionsData
            }
          }
        } catch (e) {
          // Not valid JSON, continue to next potential start
          continue
        }
      }
    }
  }
  
  console.log('[Questions] No questions detected, returning null')
  return null
}

const handleQuestionSubmit = async (answersObj) => {
  // Save question data before clearing it
  const questionData = pendingQuestionData.value
  pendingQuestionData.value = null
  
  // Format answers in a user-friendly way
  let answersText = '## My Answers\n\n'
  
  if (questionData && questionData.questions) {
    // Map through questions to show question text with answers
    questionData.questions.forEach(q => {
      const answer = answersObj[q.id]
      if (answer !== undefined && answer !== null && answer !== '') {
        answersText += `**${q.question}**\n`
        
        // Format based on answer type
        if (Array.isArray(answer)) {
          // Multichoice - show as bullet list
          answersText += answer.map(a => `- ${a}`).join('\n') + '\n\n'
        } else {
          // Single value - show as simple text
          answersText += `${answer}\n\n`
        }
      }
    })
  } else {
    // Fallback if no question data available
    answersText = 'Here are my answers:\n\n'
    Object.entries(answersObj).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        if (Array.isArray(value)) {
          answersText += `**${key}:** ${value.join(', ')}\n\n`
        } else {
          answersText += `**${key}:** ${value}\n\n`
        }
      }
    })
  }
  
  // Send the formatted answers as a new user message
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

const fetchTokenUsage = async () => {
  if (!sessionId.value) {
    tokenUsage.value = {
      tokenCount: 0,
      tokenLimit: 128000,
      usagePercentage: 0,
      shouldCompress: false,
      model: '',
      messageCount: 0,
    }
    return
  }
  
  try {
    const data = await getTokenUsage(sessionId.value)
    tokenUsage.value = {
      tokenCount: data.token_count || 0,
      tokenLimit: data.token_limit || 128000,
      usagePercentage: data.usage_percentage || 0,
      shouldCompress: data.should_compress || false,
      model: data.model || '',
      messageCount: data.message_count || 0,
    }
  } catch (error) {
    console.error('Failed to fetch token usage:', error)
  }
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
    
    // Update token usage after compression
    await fetchTokenUsage()
    
    await nextTick()
    scrollToBottom()
    alert('Context compressed successfully!')
  } catch (error) {
    console.error('Failed to compress context:', error)
    alert('Failed to compress context: ' + error.message)
  }
}

// Copy message to clipboard on double-click
const copyMessageToClipboard = async (message, index, event) => {
  // Extract plain text content from the message
  let textToCopy = ''
  
  if (message.role === 'agent') {
    // For agent messages, use displayContent if available (from computed property)
    // Otherwise extract display content from raw content
    textToCopy = message.displayContent || extractDisplayContent(message.content)
  } else {
    // For user messages, use displayContent or content
    textToCopy = message.displayContent || message.content
  }
  
  if (!textToCopy || !textToCopy.trim()) {
    return // Nothing to copy
  }
  
  try {
    // Use Clipboard API to copy
    await navigator.clipboard.writeText(textToCopy)
    
    // Capture cursor position
    copiedMessagePosition.value = {
      x: event.clientX,
      y: event.clientY
    }
    
    // Show visual feedback
    copiedMessageIndex.value = index
    setTimeout(() => {
      copiedMessageIndex.value = null
    }, 1500)
    
    console.log('Message copied to clipboard')
  } catch (error) {
    console.error('Failed to copy message:', error)
    // Fallback: try to use the older execCommand method
    try {
      const textarea = document.createElement('textarea')
      textarea.value = textToCopy
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      
      // Capture cursor position
      copiedMessagePosition.value = {
        x: event.clientX,
        y: event.clientY
      }
      
      // Show visual feedback
      copiedMessageIndex.value = index
      setTimeout(() => {
        copiedMessageIndex.value = null
      }, 1500)
    } catch (fallbackError) {
      console.error('Fallback copy also failed:', fallbackError)
    }
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
    
    // Update token usage after reset
    await fetchTokenUsage()
    
    alert('Context reset successfully!')
  } catch (error) {
    console.error('Failed to reset context:', error)
    alert('Failed to reset context: ' + error.message)
  }
}

const handleResetSession = async () => {
  if (!sessionId.value) {
    console.warn('No session ID to reset session')
    return
  }
  
  if (!confirm('COMPLETELY RESET this session?\n\nThis will:\n• Delete all conversation history\n• Delete all files in workspace\n• Delete all design documents\n\nThis CANNOT be undone!')) {
    return
  }
  
  try {
    const result = await resetSession(sessionId.value)
    
    // Clear frontend state
    messages.value = []
    toolExecutions.value = []
    selectedTool.value = null
    pendingQuestionData.value = null
    latestProgress.value = null
    designDocuments.value = []
    selectedDocument.value = null
    
    // Clear session state
    clearSessionState()
    
    // Reset pane width to default
    leftPaneWidth.value = calculateOptimalChatWidth()
    
    // Update token usage after reset
    await fetchTokenUsage()
    
    console.log('Session reset successfully:', result)
    alert(`Session reset complete!\n\nDeleted ${result.deleted_messages} messages and ${result.deleted_files} files/directories.`)
  } catch (error) {
    console.error('Failed to reset session:', error)
    alert('Failed to reset session: ' + error.message)
  }
}

// Resizable pane handlers for 3-pane layout
// Left divider (between left and center panes)
const startDraggingLeft = () => {
  isDraggingLeft.value = true
  document.addEventListener('mousemove', handleDragLeft)
  document.addEventListener('mouseup', stopDraggingLeft)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

const handleDragLeft = (e) => {
  if (!isDraggingLeft.value) return
  const container = document.querySelector('.split-container')
  if (!container) return
  const containerWidth = container.offsetWidth
  const newWidth = (e.clientX / containerWidth) * 100
  // Constrain left pane between 20% and 60%
  leftPaneWidth.value = Math.max(20, Math.min(60, newWidth))
}

const stopDraggingLeft = () => {
  isDraggingLeft.value = false
  document.removeEventListener('mousemove', handleDragLeft)
  document.removeEventListener('mouseup', stopDraggingLeft)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// Right divider (between center and right panes)
const startDraggingRight = () => {
  isDraggingRight.value = true
  document.addEventListener('mousemove', handleDragRight)
  document.addEventListener('mouseup', stopDraggingRight)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

const handleDragRight = (e) => {
  if (!isDraggingRight.value) return
  const container = document.querySelector('.split-container')
  if (!container) return
  const containerWidth = container.offsetWidth
  const mouseX = (e.clientX / containerWidth) * 100
  
  // Calculate new center width (distance from left pane end to mouse position)
  const newCenterWidth = mouseX - leftPaneWidth.value
  
  // Constrain center pane between 15% and 50%
  // Also ensure right pane has at least 20%
  const minCenter = 15
  const maxCenter = Math.min(50, 100 - leftPaneWidth.value - 20)
  centerPaneWidth.value = Math.max(minCenter, Math.min(maxCenter, newCenterWidth))
}

const stopDraggingRight = () => {
  isDraggingRight.value = false
  document.removeEventListener('mousemove', handleDragRight)
  document.removeEventListener('mouseup', stopDraggingRight)
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

// ============================================================================
// Design Documents (Plan Mode)
// ============================================================================

const fetchDesignDocuments = async () => {
  if (!sessionId.value) return
  
  try {
    const response = await fetch(`http://localhost:8000/sessions/${sessionId.value}/design/list`)
    if (response.ok) {
      const data = await response.json()
      designDocuments.value = data.documents || {}
      console.log('[Design] Fetched design documents:', Object.keys(designDocuments.value).length)
    }
  } catch (error) {
    console.error('[Design] Failed to fetch design documents:', error)
  }
}

const handleSelectDesignDoc = async (docType) => {
  console.log('[Design] Selected document:', docType)
  selectedDesignDoc.value = docType
  
  // Fetch document content
  try {
    const response = await fetch(`http://localhost:8000/sessions/${sessionId.value}/design/${docType}`)
    if (response.ok) {
      const data = await response.json()
      if (data.exists) {
        selectedDesignDocContent.value = data.content
        designDocInfo.value = {
          name: data.name,
          description: designDocuments.value[docType]?.description || ''
        }
      } else {
        selectedDesignDocContent.value = null
        designDocInfo.value = {
          name: data.name || designDocuments.value[docType]?.name || docType,
          description: designDocuments.value[docType]?.description || ''
        }
      }
    }
  } catch (error) {
    console.error('[Design] Failed to fetch document content:', error)
  }
}

const handleSaveDesignDoc = async ({ docType, content }) => {
  if (!sessionId.value || !docType) return
  
  console.log('[Design] Saving document:', docType)
  
  try {
    const response = await fetch(`http://localhost:8000/sessions/${sessionId.value}/design/${docType}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ content })
    })
    
    if (response.ok) {
      const data = await response.json()
      console.log('[Design] Document saved:', data.message)
      
      // Update local content
      selectedDesignDocContent.value = content
      
      // Refresh document list to update timestamps
      await fetchDesignDocuments()
    } else {
      console.error('[Design] Failed to save document:', await response.text())
    }
  } catch (error) {
    console.error('[Design] Failed to save document:', error)
  }
}

// Watch for mode changes and session changes to fetch design docs
watch([mode, sessionId], async ([newMode, newSessionId]) => {
  if (newMode === 'plan' && newSessionId) {
    await fetchDesignDocuments()
  }
})

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
          
          // Update or create agent message (only if we have content)
          if (agentContent && agentContent.trim()) {
            const lastMessage = messages.value[messages.value.length - 1]
            if (lastMessage && lastMessage.role === 'agent') {
              // Update existing agent message
              lastMessage.content = agentContent
            } else if (!currentToolName) {
              // Only create new message if not currently executing tools
              messages.value.push({
                role: 'agent',
                content: agentContent,
              })
            }
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
          
          // Reset currentToolName so subsequent agent messages update the last message
          currentToolName = null
          
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
          
          // In Plan Mode, refetch design documents after Agent finishes
          // (Agent may have created/updated design docs via tool_calls)
          if (mode.value === 'plan') {
            console.log('[Design] Refetching design documents after Agent response')
            await fetchDesignDocuments()
          }
          
          if (finalContent) {
            // Check for progress/plan data and store it separately
            console.log('[Progress] Checking for progress data in final content...')
            const progressData = extractProgressData(finalContent)
            if (progressData) {
              console.log('[Progress] Found progress data, storing in center pane')
              latestProgress.value = progressData
            }
            
            // Check if the agent returned structured questions
            console.log('[Questions] Checking for questions in final content...')
            console.log('[Questions] Content length:', finalContent?.length, 'First 300 chars:', finalContent?.substring(0, 300))
            const questionData = detectStructuredQuestions(finalContent)
            console.log('[Questions] Detection result:', questionData ? 'FOUND' : 'NOT FOUND')
            if (questionData) {
              console.log('[Questions] Question data structure:', JSON.stringify(questionData, null, 2))
            }
            
            // If we found questions, extract the content separately
            let displayContent = finalContent
            if (questionData) {
              try {
                const parsed = JSON.parse(finalContent.trim())
                // Remove tool_calls if present (shouldn't be in content JSON)
                if (parsed.tool_calls) {
                  console.warn('[Questions] Removing tool_calls from content JSON')
                  delete parsed.tool_calls
                }
                // If there's a separate content field, use that for display
                if (parsed.content && typeof parsed.content === 'string') {
                  // Unescape newlines and tabs
                  displayContent = parsed.content.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
                  console.log('[Questions] Extracted and unescaped display content, length:', displayContent.length)
                } else {
                  console.warn('[Questions] No content field in parsed JSON, using empty string')
                  displayContent = ''
                }
              } catch (e) {
                // Keep original content if parsing fails
                console.error('[Questions] Failed to extract content from JSON:', e.message)
                displayContent = ''
              }
              console.log('[Questions] Setting pendingQuestionData.value')
              pendingQuestionData.value = questionData
              console.log('[Questions] pendingQuestionData.value is now:', !!pendingQuestionData.value)
            }
            
            // Ensure final message is rendered with the display content
            // Only create/update message if there's actual content to display
            if (displayContent && displayContent.trim()) {
              const lastMessage = messages.value[messages.value.length - 1]
              if (lastMessage && lastMessage.role === 'agent') {
                // Update existing agent message (from token streaming)
                console.log('[Stream] Updating existing agent message with final content')
                lastMessage.content = displayContent
              } else if (agentContent === '') {
                // Only create new message if no tokens were streamed (buffered JSON response)
                console.log('[Stream] Creating new agent message for buffered JSON response')
                messages.value.push({
                  role: 'agent',
                  content: displayContent,
                })
              } else {
                console.log('[Stream] Skipping message creation (already exists from token streaming)')
              }
            } else {
              console.log('[Stream] Skipping blank message (no content to display)')
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
    // Update token usage after sending message
    await fetchTokenUsage()
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
  leftPaneWidth.value = 40 // Reset to default width
  centerPaneWidth.value = 30 // Reset center pane
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
      
      // Extract latest progress data from messages
      if (messages.value.length > 0) {
        console.log('[Progress] Checking loaded messages for progress data...')
        // Check from last to first to find the most recent progress
        for (let i = messages.value.length - 1; i >= 0; i--) {
          const msg = messages.value[i]
          if (msg.role === 'agent') {
            const progressData = extractProgressData(msg.content)
            if (progressData) {
              console.log('[Progress] Found progress data in message', i)
              latestProgress.value = progressData
              break // Use the most recent progress
            }
          }
        }
      }
      
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
      leftPaneWidth.value = 40
      centerPaneWidth.value = 30
    }
    
    await nextTick()
    scrollToBottom()
    
    // Fetch token usage after loading messages
    await fetchTokenUsage()
    
    // Fetch design documents if in plan mode
    if (mode.value === 'plan') {
      console.log('[Design] Loading design documents after session select (mode is plan)')
      await fetchDesignDocuments()
    }
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
  latestProgress.value = null
  
  // Clear state for new session
  clearSessionState()
  
  // Auto-calculate optimal chat pane width for new session
  leftPaneWidth.value = calculateOptimalChatWidth()
  
  // Reset token usage for new session
  fetchTokenUsage()
  
  // Load design documents if in plan mode
  if (mode.value === 'plan') {
    console.log('[Design] Loading design documents for new session (mode is plan)')
    fetchDesignDocuments()
  }
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
          
          // Extract latest progress data from messages
          if (messages.value.length > 0) {
            console.log('[Progress] Checking loaded messages for progress data (init)...')
            // Check from last to first to find the most recent progress
            for (let i = messages.value.length - 1; i >= 0; i--) {
              const msg = messages.value[i]
              if (msg.role === 'agent') {
                const progressData = extractProgressData(msg.content)
                if (progressData) {
                  console.log('[Progress] Found progress data in message', i, '(init)')
                  latestProgress.value = progressData
                  break // Use the most recent progress
                }
              }
            }
          }
          
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
          
          // Fetch token usage after loading messages
          await fetchTokenUsage()
          
          // Fetch design documents if in plan mode
          if (mode.value === 'plan') {
            console.log('[Design] Loading design documents on init (mode is plan)')
            await fetchDesignDocuments()
          }
        } catch (error) {
          console.error('Failed to load message history:', error)
          messages.value = []
          leftPaneWidth.value = 40
          centerPaneWidth.value = 30
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

<style scoped>
@keyframes fade-in {
  from {
    opacity: 0;
    transform: translate(-50%, -10px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

.animate-fade-in {
  animation: fade-in 0.2s ease-out;
}
</style>
