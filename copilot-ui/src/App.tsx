import React, { useState } from "react";
import axios from "axios";
import "./App.css";

interface CopilotResponse {
  answer: string;
  libraries_used: string[];
  validation_passed: boolean;
}

function App() {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<CopilotResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!query) return;

    setLoading(true);
    setError("");
    setResponse(null);

    try {
      const res = await axios.post("http://localhost:8000/api/v1/copilot/query", {
        query: query,
      });

      setResponse(res.data);
    } catch (err: any) {
      setError(
        err.response?.data?.detail || "Something went wrong. Check backend."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <h1>AI Engineering Copilot</h1>

      <div className="input-section">
        <textarea
          placeholder="Ask something like: How do I configure Celery with Redis in Docker Compose?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button onClick={handleSubmit} disabled={loading}>
          {loading ? "Thinking..." : "Run Copilot"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {response && (
        <div className="response-section">
          <h2>Answer</h2>
          <pre>{response.answer}</pre>

          <h3>Libraries Detected</h3>
          <ul>
            {response.libraries_used.map((lib, index) => (
              <li key={index}>{lib}</li>
            ))}
          </ul>

          <h3>Validation Status</h3>
          <span
            className={
              response.validation_passed ? "badge success" : "badge fail"
            }
          >
            {response.validation_passed ? "Passed" : "Failed"}
          </span>
        </div>
      )}
    </div>
  );
}

export default App;
