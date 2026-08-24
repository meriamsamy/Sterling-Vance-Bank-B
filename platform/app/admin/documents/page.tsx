'use client';

import * as React from 'react';
import {
  FileText,
  Search,
  Upload,
  Trash2,
  Loader2,
  FileUp,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { StatusBadge } from '@/components/admin/status-badge';
import {
  PageHeader,
  EmptyStateView,
  ErrorStateView,
  LoadingStateView,
} from '@/components/admin/admin-ui';
import {
  getDocuments,
  uploadDocument,
  deleteDocument,
  AdminApiError,
} from '@/lib/admin-api';
import type { AdminDocument } from '@/lib/admin-types';

type UploadState = 'idle' | 'uploading' | 'success' | 'error';

function formatBytes(bytes?: number): string {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString([], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return '—';
  }
}

export default function AdminDocumentsPage() {
  const [documents, setDocuments] = React.useState<AdminDocument[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState('');

  const [uploadState, setUploadState] = React.useState<UploadState>('idle');
  const [uploadMessage, setUploadMessage] = React.useState('');
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const [deleteTarget, setDeleteTarget] =
    React.useState<AdminDocument | null>(null);
  const [deleting, setDeleting] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getDocuments();
      setDocuments(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load documents.'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const handleFileSelect = async (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadState('uploading');
    setUploadMessage('');
    try {
      await uploadDocument(file);
      setUploadState('success');
      setUploadMessage(`${file.name} uploaded successfully.`);
      await load();
    } catch (err) {
      setUploadState('error');
      setUploadMessage(
        err instanceof AdminApiError
          ? err.message
          : 'Upload failed. Please try again.'
      );
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteDocument(deleteTarget.id);
      setDocuments((prev) =>
        prev.filter((d) => d.id !== deleteTarget.id)
      );
      setDeleteTarget(null);
    } catch (err) {
      const msg =
        err instanceof AdminApiError
          ? err.message
          : 'Failed to delete document.';
      setError(msg);
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        d.type.toLowerCase().includes(q)
    );
  }, [documents, query]);

  return (
    <div>
      <PageHeader
        title="RAG Documents"
        description="Knowledge documents used for retrieval-augmented generation."
        action={
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.txt,.md,.docx,.csv,.json"
              onChange={handleFileSelect}
            />
            <Button
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadState === 'uploading'}
              className="gap-1.5"
            >
              {uploadState === 'uploading' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileUp className="h-4 w-4" />
              )}
              Upload document
            </Button>
          </div>
        }
      />

      {uploadState === 'success' && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-md border border-success/30 bg-success/10 px-3 py-2 text-xs text-success">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {uploadMessage}
          <button
            className="ml-auto text-success/70 hover:text-success"
            onClick={() => setUploadState('idle')}
          >
            Dismiss
          </button>
        </div>
      )}

      {uploadState === 'error' && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {uploadMessage}
          <button
            className="ml-auto text-destructive/70 hover:text-destructive"
            onClick={() => setUploadState('idle')}
          >
            Dismiss
          </button>
        </div>
      )}

      {uploadState === 'uploading' && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Uploading document…
        </div>
      )}

      <div className="border-b border-border bg-background/80 px-6 py-3 backdrop-blur">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search documents by name or type…"
            className="pl-9"
          />
        </div>
      </div>

      <div className="p-6">
        {error && !deleteTarget && (
          <ErrorStateView message={error} onRetry={load} />
        )}

        {!error && loading && <LoadingStateView rows={4} />}

        {!error && !loading && filtered.length === 0 && (
          <EmptyStateView
            icon={FileText}
            title="No documents found"
            description={
              documents.length === 0
                ? 'No RAG documents are indexed yet. Upload a document to get started.'
                : 'No documents match your current search.'
            }
            action={
              documents.length === 0 ? (
                <Button
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  className="gap-1.5"
                >
                  <Upload className="h-4 w-4" />
                  Upload document
                </Button>
              ) : null
            }
          />
        )}

        {!error && !loading && filtered.length > 0 && (
          <div className="space-y-3">
            {filtered.map((doc) => (
              <Card key={doc.id} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/40">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="min-w-0">
                      <h4 className="truncate text-sm font-medium">
                        {doc.name}
                      </h4>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <Badge
                          variant="outline"
                          className="border-0 bg-muted text-[10px] text-muted-foreground"
                        >
                          {doc.type}
                        </Badge>
                        <span>Uploaded {formatDate(doc.uploadedAt)}</span>
                        {doc.sizeBytes && <span>{formatBytes(doc.sizeBytes)}</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge status={doc.status} />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setDeleteTarget(doc)}
                      className="gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete document?</DialogTitle>
            <DialogDescription>
              {deleteTarget && (
                <>
                  Permanently delete <strong>{deleteTarget.name}</strong> from
                  the RAG knowledge base? This cannot be undone.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmDelete}
              disabled={deleting}
              className="gap-1.5"
            >
              {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
              Delete document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
