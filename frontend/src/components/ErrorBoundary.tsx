import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  hasError: boolean;
}

/** Last line of defence: a rendering bug shows a friendly message instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div role="alert" className="m-6 rounded-md border-2 border-red-800 bg-red-50 p-4">
          <h1 className="text-lg font-bold">Something went wrong.</h1>
          <p className="mt-1">Please reload the page to try again.</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="focus-ring mt-3 rounded-md border-2 border-red-800 bg-white px-3 py-1 font-semibold"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
