export class ApiError extends Error {
  readonly code: string;
  readonly payload?: unknown;
  readonly status: number;

  constructor({
    code,
    message,
    payload,
    status,
  }: {
    code: string;
    message: string;
    payload?: unknown;
    status: number;
  }) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.payload = payload;
    this.status = status;
  }
}

export function apiErrorFromResponse({
  payload,
  status,
  statusText,
}: {
  payload: unknown;
  status: number;
  statusText: string;
}): ApiError {
  if (isRecord(payload)) {
    const error = payload.error;
    const message = payload.message;
    if (typeof error === "string" && typeof message === "string") {
      return new ApiError({ code: error, message, payload, status });
    }
    if (isRecord(error) && typeof error.code === "string" && typeof error.message === "string") {
      return new ApiError({ code: error.code, message: error.message, payload, status });
    }
  }

  const message = typeof payload === "string" && payload ? payload : statusText || "Request failed";
  return new ApiError({ code: "http_error", message, payload, status });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
