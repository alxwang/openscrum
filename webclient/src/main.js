import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
// Using minimal PrimeVue setup - Tailwind handles most styling
import 'primeicons/primeicons.css'
import App from './App.vue'
import './style.css'

const app = createApp(App)

// Configure PrimeVue (minimal setup - we're using Tailwind for styling)
app.use(PrimeVue, {
  unstyled: false, // Use default PrimeVue styles where needed
})

app.mount('#app')
