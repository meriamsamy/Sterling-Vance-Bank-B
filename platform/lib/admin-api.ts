import type {
  AdminAgent,
  AdminTool,
  AdminDocument,
  AgentToolAssignment,
  AvailableTool,
  DashboardSummary,
} from '@/lib/admin-types';

const ADMIN_API_BASE =
  process.env.NEXT_PUBLIC_ADMIN_API_URL ?? '/api/admin';

class AdminApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = 'AdminApiError';
    this.status = status;
  }
}

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${ADMIN_API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (err) {
    throw new AdminApiError(
      'Unable to reach the admin backend. Integration pending.',
      0
    );
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* keep default */
    }
    throw new AdminApiError(detail, res.status);
  }

  return res.json() as Promise<T>;
}

export { AdminApiError };

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return adminFetch<DashboardSummary>('/dashboard/summary');
}

export async function getAgents(): Promise<AdminAgent[]> {
  return adminFetch<AdminAgent[]>('/agents');
}

export async function getAgent(agentId: string): Promise<AdminAgent> {
  return adminFetch<AdminAgent>(`/agents/${encodeURIComponent(agentId)}`);
}

export async function getAgentTools(
  agentId: string
): Promise<AgentToolAssignment[]> {
  return adminFetch<AgentToolAssignment[]>(
    `/agents/${encodeURIComponent(agentId)}/tools`
  );
}

export async function getAvailableTools(
  agentId: string
): Promise<AvailableTool[]> {
  return adminFetch<AvailableTool[]>(
    `/agents/${encodeURIComponent(agentId)}/available-tools`
  );
}

export async function assignToolToAgent(
  agentId: string,
  toolId: string
): Promise<void> {
  await adminFetch<void>(
    `/agents/${encodeURIComponent(agentId)}/tools`,
    {
      method: 'POST',
      body: JSON.stringify({ toolId }),
    }
  );
}

export async function removeToolFromAgent(
  agentId: string,
  toolId: string
): Promise<void> {
  await adminFetch<void>(
    `/agents/${encodeURIComponent(agentId)}/tools/${encodeURIComponent(toolId)}`,
    { method: 'DELETE' }
  );
}

export async function getTools(): Promise<AdminTool[]> {
  return adminFetch<AdminTool[]>('/tools');
}

export async function getTool(toolId: string): Promise<AdminTool> {
  return adminFetch<AdminTool>(`/tools/${encodeURIComponent(toolId)}`);
}

export async function getDocuments(): Promise<AdminDocument[]> {
  return adminFetch<AdminDocument[]>('/documents');
}

export async function uploadDocument(
  file: File
): Promise<AdminDocument> {
  const formData = new FormData();
  formData.append('file', file);
  let res: Response;
  try {
    res = await fetch(`${ADMIN_API_BASE}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
  } catch {
    throw new AdminApiError(
      'Unable to reach the admin backend for upload. Integration pending.',
      0
    );
  }
  if (!res.ok) {
    throw new AdminApiError(`Upload failed (${res.status})`, res.status);
  }
  return res.json() as Promise<AdminDocument>;
}

export async function deleteDocument(documentId: string): Promise<void> {
  await adminFetch<void>(
    `/documents/${encodeURIComponent(documentId)}`,
    { method: 'DELETE' }
  );
}
