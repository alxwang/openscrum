<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-surface-dark rounded-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col border border-surface">
      <!-- Header -->
      <div class="px-6 py-4 border-b border-surface">
        <h2 class="text-xl font-semibold text-text-inverse">Permission Request</h2>
        <p class="text-sm text-text-muted mt-1">The agent is requesting permission to perform an action</p>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-4 space-y-4">
        <!-- Tool Information -->
        <div>
          <h3 class="text-sm font-medium text-text-muted mb-1">Tool</h3>
          <p class="text-white font-mono text-sm bg-accent/20 px-3 py-2 rounded-lg border border-accent">
            {{ permission.permission || permission.tool_name || 'NO TOOL NAME' }}
          </p>
        </div>

        <!-- Command -->
        <div v-if="permission.metadata?.args?.command">
          <h3 class="text-sm font-medium text-text-muted mb-1">Command</h3>
          <pre class="text-white text-sm bg-background-dark px-3 py-2 rounded-lg overflow-x-auto">{{ permission.metadata.args.command }}</pre>
        </div>

        <!-- Description -->
        <div v-if="permission.metadata?.args?.description">
          <h3 class="text-sm font-medium text-text-muted mb-1">Description</h3>
          <p class="text-text-inverse px-3 py-2 bg-background-dark rounded-lg">
            {{ permission.metadata.args.description }}
          </p>
        </div>

        <!-- Working Directory -->
        <div v-if="permission.metadata?.args && 'workdir' in permission.metadata.args">
          <h3 class="text-sm font-medium text-text-muted mb-1">Working Directory</h3>
          <p class="text-text-inverse px-3 py-2 bg-background-dark rounded-lg font-mono">
            {{ permission.metadata.args.workdir || '(default/current directory)' }}
          </p>
        </div>

        <!-- Timeout -->
        <div v-if="permission.metadata?.args && 'timeout' in permission.metadata.args">
          <h3 class="text-sm font-medium text-text-muted mb-1">Timeout</h3>
          <p class="text-text-inverse px-3 py-2 bg-background-dark rounded-lg">
            {{ permission.metadata.args.timeout ? `${Math.round(permission.metadata.args.timeout / 1000)}s` : '120s (2 minutes default)' }}
          </p>
        </div>

        <!-- Action Description (fallback) -->
        <div v-if="permission.action && !permission.metadata?.args?.description">
          <h3 class="text-sm font-medium text-text-muted mb-1">Action</h3>
          <p class="text-text-inverse px-3 py-2 bg-background-dark rounded-lg">
            {{ permission.action }}
          </p>
        </div>

        <!-- Parameters -->
        <div v-if="permission.params && Object.keys(permission.params).length > 0">
          <h3 class="text-sm font-medium text-text-muted mb-2">Parameters</h3>
          <div class="bg-background-dark rounded-lg p-3 space-y-2">
            <div v-for="(value, key) in permission.params" :key="key" class="flex flex-col gap-1">
              <span class="text-xs font-medium text-accent">{{ key }}</span>
              <span class="text-sm text-text-inverse font-mono break-all">{{ formatValue(value) }}</span>
            </div>
          </div>
        </div>

        <!-- All other metadata args -->
        <div v-if="permission.metadata?.args">
          <template v-for="(value, key) in permission.metadata.args" :key="key">
            <div v-if="key !== 'command' && key !== 'description' && key !== 'workdir' && key !== 'timeout'" class="mb-3">
              <h3 class="text-sm font-medium text-text-muted mb-1">{{ key }}</h3>
              <div class="bg-background-dark rounded-lg p-3">
                <span class="text-sm text-text-inverse font-mono break-all">{{ formatValue(value) }}</span>
              </div>
            </div>
          </template>
        </div>

        <!-- Reason -->
        <div v-if="permission.reason">
          <h3 class="text-sm font-medium text-text-muted mb-1">Reason</h3>
          <p class="text-text-inverse px-3 py-2 bg-background-dark rounded-lg">
            {{ permission.reason }}
          </p>
        </div>

        <!-- Request ID -->
        <div class="text-xs text-text-muted">
          Request ID: <span class="font-mono">{{ permission.id || permission.request_id }}</span>
        </div>
      </div>

      <!-- Actions -->
      <div class="px-6 py-4 border-t border-surface flex flex-wrap gap-3">
        <button
          @click="$emit('reply', 'once')"
          class="flex-1 min-w-[120px] px-4 py-2.5 bg-accent hover:bg-accent-hover rounded-lg font-medium transition-colors"
        >
          Allow Once
        </button>
        <button
          @click="$emit('reply', 'always')"
          class="flex-1 min-w-[120px] px-4 py-2.5 bg-green-600 hover:bg-green-700 rounded-lg font-medium transition-colors"
        >
          Always Allow
        </button>
        <button
          @click="$emit('reply', 'deny')"
          class="flex-1 min-w-[120px] px-4 py-2.5 bg-red-600 hover:bg-red-700 rounded-lg font-medium transition-colors text-white"
        >
          Deny
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  permission: {
    type: Object,
    required: true,
  },
})

defineEmits(['reply'])

const formatValue = (value) => {
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}
</script>
