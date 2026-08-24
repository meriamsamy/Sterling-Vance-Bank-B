'use client';

import * as React from 'react';
import { Sidebar } from '@/components/sidebar';
import { AgentHeader } from '@/components/agent-header';
import { EmptyState } from '@/components/empty-state';
import { ChatInput, ScrollToBottomButton } from '@/components/chat-input';
import {
  MessageBubble,
  TypingIndicator,
  type ChatMessage,
} from '@/components/message-bubble';
import { AGENTS, type AgentId } from '@/lib/agents';
import { cn } from '@/lib/utils';

function generateThreadId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `thread_${Date.now().toString(36)}_${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

export default function Home() {
  const [activeAgentId, setActiveAgentId] = React.useState<AgentId>(
    'customer-risk-monitoring'
  );
  const [threadId, setThreadId] = React.useState<string | null>(null);
  const [threadCreatedAt, setThreadCreatedAt] = React.useState<number | null>(
    null
  );
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const scrollRef = React.useRef<HTMLDivElement>(null);
  const [showScrollBtn, setShowScrollBtn] = React.useState(false);

  const activeAgent = AGENTS[activeAgentId];

  const scrollToBottom = React.useCallback((smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }, []);

  React.useEffect(() => {
    scrollToBottom(true);
  }, [messages, isSending, scrollToBottom]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setShowScrollBtn(distance > 120);
  };

  const resetThread = () => {
    setThreadId(null);
    setThreadCreatedAt(null);
    setMessages([]);
    setError(null);
  };

  const handleAgentChange = (id: AgentId) => {
    if (id === activeAgentId) return;
    setActiveAgentId(id);
    resetThread();
  };

  const handleNewThread = () => {
    resetThread();
  };

  const sendMessage = async (text: string) => {
    setError(null);

    const currentThreadId = threadId ?? generateThreadId();
    if (!threadId) {
      setThreadId(currentThreadId);
      setThreadCreatedAt(Date.now());
    }

    const userMsg: ChatMessage = {
      id: `${Date.now()}_u`,
      role: 'user',
      content: text,
      createdAt: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsSending(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_name: activeAgentId,
          message: text,
          thread_id: currentThreadId,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const detail =
          data.fallback ??
          data.detail ??
          data.error ??
          'The agent could not process your request.';
        throw new Error(detail);
      }

      const aiMsg: ChatMessage = {
        id: `${Date.now()}_a`,
        role: 'assistant',
        content: data.response,
        createdAt: Date.now(),
      };
      setMessages((prev) => [...prev, aiMsg]);

      if (data.thread_id) {
        setThreadId(data.thread_id);
      }
    } catch (err) {
      const detail =
        err instanceof Error ? err.message : 'Unexpected error occurred.';
      setError(detail);
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}_e`,
          role: 'assistant',
          content: `Unable to reach the agent. ${detail}`,
          createdAt: Date.now(),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <Sidebar
        activeAgentId={activeAgentId}
        onAgentChange={handleAgentChange}
        threadId={threadId}
        threadCreatedAt={threadCreatedAt}
        messageCount={messages.length}
        onNewThread={handleNewThread}
      />

      <main className="flex h-full flex-1 flex-col">
        <AgentHeader
          agent={activeAgent}
          threadId={threadId}
          online={!isSending || true}
        />

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className={cn(
            'relative flex-1 overflow-y-auto scrollbar-thin',
            messages.length === 0 && 'flex items-center'
          )}
        >
          {messages.length === 0 ? (
            <EmptyState
              agent={activeAgent}
              onSuggestionClick={sendMessage}
            />
          ) : (
            <div className="mx-auto max-w-3xl py-4">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
              {isSending && <TypingIndicator />}
            </div>
          )}
        </div>

        <ScrollToBottomButton
          visible={showScrollBtn && messages.length > 0}
          onClick={() => scrollToBottom(true)}
        />

        {error && (
          <div className="mx-auto max-w-3xl px-4">
            <p className="mb-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          </div>
        )}

        <ChatInput onSend={sendMessage} disabled={isSending} />
      </main>
    </div>
  );
}
