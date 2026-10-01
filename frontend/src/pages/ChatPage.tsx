import { useState, type FormEvent } from "react";

import type { AgentHistoryTurn, AgentStep } from "@/api/types";
import { useAskAgent } from "@/hooks/useAgent";
import { cn } from "@/lib/cn";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[];
}

const EXAMPLE_QUESTIONS = [
  "Who should I keep this year?",
  "Is my team good this year?",
  "What's the best available RB right now?",
];

function ToolTrace({ steps }: { steps: AgentStep[] }) {
  const [open, setOpen] = useState(false);

  if (steps.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        className="text-xs font-medium text-hunter underline-offset-2 hover:underline dark:text-celadon"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide reasoning" : "Show reasoning"} ({steps.length} tool call{steps.length === 1 ? "" : "s"})
      </button>
      {open && (
        <ol className="mt-2 space-y-2 border-l border-neutral-200 pl-3 dark:border-neutral-700">
          {steps.map((step, i) => (
            <li key={i} className="text-xs">
              <span className={cn("font-mono font-medium", step.error && "text-rose-600 dark:text-rose-400")}>
                {step.tool_name}({JSON.stringify(step.arguments)})
              </span>
              <p className="mt-0.5 whitespace-pre-wrap text-neutral-500">{step.output_preview}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-card px-3 py-2 text-sm",
          isUser ? "bg-hunter text-white" : "card",
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {!isUser && message.steps && <ToolTrace steps={message.steps} />}
      </div>
    </div>
  );
}

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const ask = useAskAgent();

  function send(question: string) {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;

    const history: AgentHistoryTurn[] = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");

    ask.mutate(
      { question: trimmed, history },
      {
        onSuccess: (result) => {
          setMessages((prev) => [...prev, { role: "assistant", content: result.answer, steps: result.steps }]);
        },
        onError: (error) => {
          setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${error.message}` }]);
        },
      },
    );
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    send(input);
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col md:h-[calc(100vh-3rem)]">
      <h1 className="page-title">Chat</h1>

      {messages.length === 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((question) => (
            <button key={question} className="btn-secondary" onClick={() => send(question)}>
              {question}
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 flex-1 space-y-3 overflow-y-auto pb-2">
        {messages.map((message, i) => (
          <Bubble key={i} message={message} />
        ))}
        {ask.isPending && (
          <div className="flex justify-start">
            <div className="card text-sm text-neutral-500">Thinking...</div>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="mt-3 flex gap-2">
        <input
          className="input"
          placeholder="Ask about keepers, trades, your roster..."
          value={input}
          onChange={(event) => setInput(event.target.value)}
          disabled={ask.isPending}
        />
        <button type="submit" className="btn-primary" disabled={ask.isPending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
