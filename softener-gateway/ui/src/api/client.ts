import { apiUrl } from "./config";
import { apiErrorFromResponse } from "./errors";

type ApiMethod = "DELETE" | "GET" | "PATCH" | "POST" | "PUT";

export type ApiResponse<TData> = {
  data: TData;
  status: number;
};

export type ApiRequestOptions<TBody = unknown> = {
  acceptedStatuses?: readonly number[];
  body?: TBody;
  headers?: HeadersInit;
  method?: ApiMethod;
  signal?: AbortSignal;
};

export async function apiRequest<TResponse, TBody = unknown>(
  path: string,
  options: ApiRequestOptions<TBody> = {},
): Promise<ApiResponse<TResponse>> {
  const { acceptedStatuses, body, headers, method = "GET", signal } = options;
  const requestHeaders = new Headers(headers);
  const requestInit: RequestInit = {
    headers: requestHeaders,
    method,
    signal,
  };

  requestHeaders.set("Accept", requestHeaders.get("Accept") ?? "application/json");

  if (body !== undefined) {
    requestHeaders.set("Content-Type", requestHeaders.get("Content-Type") ?? "application/json");
    requestInit.body = JSON.stringify(body);
  }

  const response = await fetch(apiUrl(path), requestInit);
  const payload = await readResponsePayload(response);

  if (!response.ok && !acceptedStatuses?.includes(response.status)) {
    throw apiErrorFromResponse({
      payload,
      status: response.status,
      statusText: response.statusText,
    });
  }

  return {
    data: payload as TResponse,
    status: response.status,
  };
}

export function apiGet<TResponse>(
  path: string,
  options: Omit<ApiRequestOptions, "body" | "method"> = {},
): Promise<ApiResponse<TResponse>> {
  return apiRequest<TResponse>(path, { ...options, method: "GET" });
}

export function apiPost<TBody, TResponse>(
  path: string,
  body: TBody,
  options: Omit<ApiRequestOptions<TBody>, "body" | "method"> = {},
): Promise<ApiResponse<TResponse>> {
  return apiRequest<TResponse, TBody>(path, { ...options, body, method: "POST" });
}

async function readResponsePayload(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined;
  }

  const text = await response.text();
  if (!text) {
    return undefined;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}
