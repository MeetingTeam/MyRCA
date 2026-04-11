export default function PropagationChain({ chain }) {
  if (!chain || chain.length === 0) return <p className="text-gray-500">No propagation chain available</p>

  // chain may be ["A → B → C"] or ["A", "B", "C"]
  const services = chain.length === 1 && chain[0].includes('→')
    ? chain[0].split('→').map(s => s.trim())
    : chain

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {services.map((svc, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className={`px-3 py-2 rounded-lg border text-sm font-mono ${
            i === 0
              ? 'bg-red-900/40 border-red-500 text-red-300'
              : 'bg-dark-700 border-gray-600 text-gray-300'
          }`}>
            {svc}
          </div>
          {i < services.length - 1 && (
            <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          )}
        </div>
      ))}
    </div>
  )
}
