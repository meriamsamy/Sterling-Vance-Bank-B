'use client';

import React, { useState, useEffect, useRef } from 'react';

type AgentId = 'customer-risk-monitoring' | 'planning-decomposition' | 'memory-rag' | 'sanctions-change';

interface Message {
  sender: 'user' | 'agent';
  text: string;
}

const AGENTS: { id: AgentId; name: string; description: string }[] = [
  {
    id: 'customer-risk-monitoring',
    name: 'Customer Risk Monitoring',
    description: 'Analyzes customer accounts and transactions for risk monitoring.',
  },
  {
    id: 'planning-decomposition',
    name: 'Planning & Decomposition',
    description: 'Decomposes complex tasks and builds execution workflows (DAGs).',
  },
  {
    id: 'memory-rag',
    name: 'Memory & RAG',
    description: 'Retrieves context and information from databases and memory.',
  },
  {
    id: 'sanctions-change',
    name: 'Sanctions Change Monitoring',
    description: 'Monitors sanctions changes and re-evaluates affected wire reviews.',
  },
];

export default function UnifiedAgentChatPlatform() {
  const [selectedAgent, setSelectedAgent] = useState<AgentId>('customer-risk-monitoring');
  const [sessions, setSessions] = useState<Record<AgentId, { threadId: string; messages: Message[] }>>({
  'customer-risk-monitoring': {
    threadId: crypto.randomUUID(),
    messages: [
      {
        sender: 'agent',
        text: 'Hello. I am the Customer Risk Monitoring agent. How can I assist you today?',
      },
    ],
  },

  'planning-decomposition': {
    threadId: crypto.randomUUID(),
    messages: [
      {
        sender: 'agent',
        text: 'Ready to decompose tasks and build execution plans.',
      },
    ],
  },

  'memory-rag': {
    threadId: crypto.randomUUID(),
    messages: [
      {
        sender: 'agent',
        text: 'I can retrieve data and search memory to help you.',
      },
    ],
  },

  'sanctions-change': {
    threadId: crypto.randomUUID(),
    messages: [
      {
        sender: 'agent',
        text: 'Sanctions Change Monitoring is ready. I can review sanctions-related changes and affected wire transfers.',
      },
    ],
  },
});

  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const currentSession = sessions[selectedAgent];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentSession.messages, loading]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMsg = input.trim();
    setInput('');

    // Update messages locally for the user
    setSessions((prev) => ({
      ...prev,
      [selectedAgent]: {
        ...prev[selectedAgent],
        messages: [...prev[selectedAgent].messages, { sender: 'user', text: userMsg }],
      },
    }));

    setLoading(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_name: selectedAgent,
          message: userMsg,
          thread_id: currentSession.threadId,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || 'An error occurred while connecting to the agent');
      }

      // Add the real agent response
      setSessions((prev) => ({
        ...prev,
        [selectedAgent]: {
          ...prev[selectedAgent],
          messages: [...prev[selectedAgent].messages, { sender: 'agent', text: data.response }],
        },
      }));
    } catch (err: any) {
      setSessions((prev) => ({
        ...prev,
        [selectedAgent]: {
          ...prev[selectedAgent],
          messages: [...prev[selectedAgent].messages, { sender: 'agent', text: `Error: ${err.message}` }],
        },
      }));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-gray-900 text-white">
      {/* Sidebar for switching agents */}
      <div className="w-80 border-r border-gray-800 p-4 flex flex-col gap-2">
        <h2 className="text-lg font-bold mb-4 text-blue-400">Sterling & Vance Platform</h2>
        <p className="text-xs text-gray-400 mb-2">Select an agent to start (isolated sessions):</p>
        {AGENTS.map((agent) => (
          <button
            key={agent.id}
            onClick={() => setSelectedAgent(agent.id)}
            className={`p-3 rounded-lg text-left transition-all ${
              selectedAgent === agent.id ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            <div className="font-semibold text-sm">{agent.name}</div>
            <div className="text-xs opacity-75 truncate mt-1">{agent.description}</div>
          </button>
        ))}
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col h-full">
        <header className="p-4 border-b border-gray-800 bg-gray-900 flex justify-between items-center">
          <div>
            <h3 className="font-bold capitalize">{selectedAgent.replace(/-/g, ' ')}</h3>
            <span className="text-xs text-green-400">● Connected & Ready (Session Isolated)</span>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6 space-y-4 bg-gray-950">
          {currentSession.messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-lg p-3 rounded-xl text-sm ${
                  msg.sender === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-200'
                }`}
              >
                {msg.text}
              </div>
            </div>
          ))}
          {loading && <div className="text-gray-500 text-sm animate-pulse">Agent is typing...</div>}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSendMessage} className="p-4 border-t border-gray-800 bg-gray-900 flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={`Chat with ${selectedAgent}...`}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-blue-600 px-6 py-3 rounded-lg font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}