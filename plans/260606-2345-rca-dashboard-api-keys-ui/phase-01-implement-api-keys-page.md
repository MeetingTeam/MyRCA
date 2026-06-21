---
phase: 1
title: "Implement API Keys Page"
status: completed
priority: P1
effort: "30m"
dependencies: []
---

# Phase 1: Implement API Keys Page

## Overview

Create `api-keys-page.jsx` component with form to add/manage LLM API keys, stored in localStorage.

## Requirements

- Form to add API key with provider selection
- List of configured providers with masked keys
- Delete functionality
- Active model selection
- Dark theme matching existing dashboard

## Related Code Files

- Create: `src/components/api-keys-page.jsx`
- Modify: `src/App.jsx` (update route)

## Implementation Steps

### Step 1: Create API Keys Page Component

Create `src/components/api-keys-page.jsx`:

```jsx
import { useState, useEffect } from 'react'
import { Key, Plus, Trash2, Check } from 'lucide-react'

const PROVIDERS = [
  { id: 'anthropic', name: 'Anthropic', models: ['claude-sonnet-4-6', 'claude-opus-4-5', 'claude-3-5-sonnet'] },
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o', 'gpt-4-turbo', 'o1-preview'] },
  { id: 'google', name: 'Google AI', models: ['gemini-2.0-flash', 'gemini-pro'] },
]

const DEFAULT_ACTIVE_MODEL = 'anthropic:claude-sonnet-4-6'

export default function ApiKeysPage() {
  const [keys, setKeys] = useState({})
  const [activeModel, setActiveModel] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [formData, setFormData] = useState({ provider: '', apiKey: '', model: '' })

  // Load from localStorage (default: Claude Sonnet 4.6)
  useEffect(() => {
    const saved = localStorage.getItem('rca-api-keys')
    const savedModel = localStorage.getItem('rca-active-model')
    if (saved) setKeys(JSON.parse(saved))
    setActiveModel(savedModel || DEFAULT_ACTIVE_MODEL)
  }, [])

  // Save to localStorage
  const saveKey = () => {
    const newKeys = { ...keys, [formData.provider]: { apiKey: formData.apiKey, model: formData.model } }
    setKeys(newKeys)
    localStorage.setItem('rca-api-keys', JSON.stringify(newKeys))
    setShowForm(false)
    setFormData({ provider: '', apiKey: '', model: '' })
  }

  const deleteKey = (provider) => {
    const newKeys = { ...keys }
    delete newKeys[provider]
    setKeys(newKeys)
    localStorage.setItem('rca-api-keys', JSON.stringify(newKeys))
  }

  const setActive = (provider, model) => {
    const modelKey = `${provider}:${model}`
    setActiveModel(modelKey)
    localStorage.setItem('rca-active-model', modelKey)
  }

  const maskKey = (key) => key ? `${key.slice(0, 8)}...${key.slice(-4)}` : ''

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">API Keys</h1>
        <button onClick={() => setShowForm(true)} className="...">
          <Plus size={16} /> Add Key
        </button>
      </div>

      {/* Add Key Form Modal */}
      {showForm && (
        <div className="...">
          {/* Provider select, API key input, Model select, Save button */}
        </div>
      )}

      {/* Configured Keys List */}
      <div className="space-y-4">
        {Object.entries(keys).map(([provider, config]) => (
          <div key={provider} className="...">
            {/* Provider name, masked key, model, active indicator, delete button */}
          </div>
        ))}
      </div>
    </div>
  )
}
```

### Step 2: Update App.jsx Route

Replace PlaceholderPage with ApiKeysPage:

```jsx
import ApiKeysPage from './components/api-keys-page'

// In Routes:
<Route path="/api-keys" element={<ApiKeysPage />} />
```

## Success Criteria

- [ ] Add API key form works (provider, key, model)
- [ ] Keys persisted in localStorage
- [ ] Keys displayed with masked values
- [ ] Delete key functionality works
- [ ] Active model selection works
- [ ] Dark theme matches existing dashboard
