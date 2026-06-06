import { Construction } from 'lucide-react'

export default function PlaceholderPage({ title, description }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <Construction size={64} className="text-gray-600 mb-4" />
      <h1 className="text-2xl font-bold text-gray-300 mb-2">{title}</h1>
      <p className="text-gray-500 max-w-md">{description}</p>
      <span className="mt-4 px-3 py-1 bg-yellow-900/30 text-yellow-500 rounded-full text-sm">
        Coming Soon
      </span>
    </div>
  )
}
