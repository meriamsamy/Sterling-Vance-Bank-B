export type AgentStatus = 'operational' | 'idle' | 'offline' | 'error';
export type ToolStatus = 'active' | 'disabled' | 'error';
export type DocumentStatus =
  | 'queued'
  | 'processing'
  | 'indexed'
  | 'failed';
export type ServerStatus = 'operational' | 'degraded' | 'offline';

export interface AdminAgent {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  assignedToolCount: number;
  capabilities: string[];
  icon?: string;
  lastActiveAt?: string;
}

export interface AdminTool {
  id: string;
  name: string;
  description: string;
  category: string;
  status: ToolStatus;
  assignedAgentIds: string[];
  assignedAgentNames: string[];
}

export interface AdminDocument {
  id: string;
  name: string;
  type: string;
  status: DocumentStatus;
  uploadedAt: string;
  sizeBytes?: number;
}

export interface AgentToolAssignment {
  toolId: string;
  toolName: string;
  toolDescription: string;
  category: string;
  status: ToolStatus;
}

export interface AvailableTool {
  toolId: string;
  toolName: string;
  toolDescription: string;
  category: string;
  alreadyAssigned: boolean;
}

export interface DashboardSummary {
  totalAgents: number;
  activeAgents: number;
  totalTools: number;
  assignedTools: number;
  ragDocuments: number;
  mcpServerStatus: ServerStatus;
}

export interface Paginated<T> {
  items: T[];
  total: number;
}
