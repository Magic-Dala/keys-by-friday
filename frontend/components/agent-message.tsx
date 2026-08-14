import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface AgentMessageProps {
  children: string;
}

export function AgentMessage({ children }: AgentMessageProps) {
  return (
    <div className="agentMessage">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children: heading }) => <h2>{heading}</h2>,
          a: ({ children: label, href, title }) => (
            <a href={href} title={title} target="_blank" rel="noopener noreferrer">
              {label}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
