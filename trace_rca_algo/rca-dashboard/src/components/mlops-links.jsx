import { ExternalLink, BarChart2, Wind, FlaskConical } from 'lucide-react'

const tools = [
  {
    id: 'evidently',
    name: 'Evidently',
    description: 'ML model monitoring and data drift detection',
    icon: BarChart2,
    url: 'http://34.226.226.116:30800/',
  },
  {
    id: 'airflow',
    name: 'Airflow',
    description: 'Workflow orchestration and DAG management',
    icon: Wind,
    url: 'http://34.226.226.116:30380/',
  },
  {
    id: 'mlflow',
    name: 'MLflow',
    description: 'ML experiment tracking and model registry',
    icon: FlaskConical,
    url: 'http://34.226.226.116:30002/',
  },
]

export default function MlopsLinks() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">MLOps Tools</h1>
      <p className="text-gray-400 mb-8">
        Access MLOps tools for model monitoring, workflow orchestration, and experiment tracking.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {tools.map(tool => (
          <a
            key={tool.id}
            href={tool.url}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-dark-800 border border-gray-700 rounded-lg p-6 hover:border-blue-500 hover:bg-dark-700 transition group"
          >
            <div className="flex items-center gap-3 mb-3">
              <tool.icon size={24} className="text-blue-400" />
              <h2 className="text-lg font-semibold">{tool.name}</h2>
              <ExternalLink size={16} className="text-gray-500 group-hover:text-blue-400 ml-auto" />
            </div>
            <p className="text-sm text-gray-400">{tool.description}</p>
          </a>
        ))}
      </div>
    </div>
  )
}
