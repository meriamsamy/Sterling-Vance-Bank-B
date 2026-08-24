'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Bot, User } from 'lucide-react';

export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: number;
}

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div
      className={cn(
        'flex w-full gap-3 px-4 py-3 animate-fade-in-up',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      <Avatar
        className={cn(
          'h-8 w-8 shrink-0 border',
          isUser
            ? 'border-border bg-secondary'
            : 'border-primary/30 bg-primary/10'
        )}
      >
        <AvatarFallback
          className={cn(
            'bg-transparent',
            isUser ? 'text-foreground' : 'text-primary'
          )}
        >
          {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
        </AvatarFallback>
      </Avatar>
      <div
        className={cn(
          'flex max-w-[78%] flex-col gap-1',
          isUser ? 'items-end' : 'items-start'
        )}
      >
        <span className="px-1 text-[11px] font-medium text-muted-foreground">
          {isUser ? 'You' : 'Agent'}
        </span>
        <div
          className={cn(
            'whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm',
            isUser
              ? 'rounded-tr-sm bg-primary text-primary-foreground'
              : 'rounded-tl-sm bg-card text-card-foreground border border-border'
          )}
        >
          {message.content}
        </div>
      </div>
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="flex w-full gap-3 px-4 py-3">
      <Avatar className="h-8 w-8 shrink-0 border border-primary/30 bg-primary/10">
        <AvatarFallback className="bg-transparent text-primary">
          <Bot className="h-4 w-4" />
        </AvatarFallback>
      </Avatar>
      <div className="flex flex-col gap-1">
        <span className="px-1 text-[11px] font-medium text-muted-foreground">
          Agent
        </span>
        <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3">
          <span className="typing-dot h-2 w-2 rounded-full bg-primary" />
          <span
            className="typing-dot h-2 w-2 rounded-full bg-primary"
            style={{ animationDelay: '0.15s' }}
          />
          <span
            className="typing-dot h-2 w-2 rounded-full bg-primary"
            style={{ animationDelay: '0.3s' }}
          />
        </div>
      </div>
    </div>
  );
}
