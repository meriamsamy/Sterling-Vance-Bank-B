export type AgentId =
  | 'customer-risk-monitoring'
  | 'planning-decomposition'
  | 'memory-rag';

export interface AgentDefinition {
  id: AgentId;
  name: string;
  shortName: string;
  description: string;
  capabilities: string[];
  /** lucide-react icon name rendered by the sidebar */
  icon:
    | 'ShieldAlert'
    | 'Workflow'
    | 'BrainCircuit';
  accentClass: string;
  status: 'operational' | 'operational' | 'operational';
}

export const AGENTS: Record<AgentId, AgentDefinition> = {
  'customer-risk-monitoring': {
    id: 'customer-risk-monitoring',
    name: 'Customer Risk Monitoring Agent',
    shortName: 'Risk Monitoring',
    description:
      'Continuously monitors customer portfolios for emerging credit, market, and fraud risk signals.',
    capabilities: [
      'Real-time risk scoring',
      'Anomaly detection',
      'Alert escalation',
    ],
    icon: 'ShieldAlert',
    accentClass: 'text-rose-500',
    status: 'operational',
  },
  'planning-decomposition': {
    id: 'planning-decomposition',
    name: 'Planning & Decomposition Agent',
    shortName: 'Planning',
    description:
      'Breaks complex banking workflows into structured, executable sub-tasks with dependencies.',
    capabilities: [
      'Task decomposition',
      'Dependency mapping',
      'Execution planning',
    ],
    icon: 'Workflow',
    accentClass: 'text-sky-500',
    status: 'operational',
  },
  'memory-rag': {
    id: 'memory-rag',
    name: 'Memory & RAG Agent',
    shortName: 'Memory & RAG',
    description:
      'Retrieves institutional knowledge and maintains conversational memory across sessions.',
    capabilities: [
      'Knowledge retrieval',
      'Contextual recall',
      'Policy lookup',
    ],
    icon: 'BrainCircuit',
    accentClass: 'text-emerald-500',
    status: 'operational',
  },
};

export const AGENT_LIST = Object.values(AGENTS);

export function getAgent(id: AgentId): AgentDefinition {
  return AGENTS[id];
}
