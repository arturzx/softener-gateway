import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  ControlCommand,
  DeviceInfo,
  Settings,
  SoftenerSnapshot,
  State,
} from "../shared/types/softener";
import { apiGet, apiPost } from "./client";
import { queryKeys } from "./queryKeys";

type OpenApiSchema = {
  paths?: {
    "/control/{command}"?: {
      post?: {
        parameters?: {
          schema?: {
            enum?: string[];
          };
        }[];
      };
    };
  };
};

export type ControlPayload = Record<string, unknown>;

export async function getSoftenerSnapshot(signal?: AbortSignal): Promise<SoftenerSnapshot> {
  const [device, state, settings] = await Promise.all([
    apiGet<DeviceInfo>("device", { signal }),
    apiGet<State>("state", { signal }),
    apiGet<Settings>("settings", { signal }),
  ]);

  return {
    device: device.data,
    settings: settings.data,
    state: state.data,
    updatedAt: new Date().toISOString(),
  };
}

export async function getControlCommands(signal?: AbortSignal): Promise<ControlCommand[]> {
  const response = await apiGet<OpenApiSchema>("openapi.json", { signal });
  const enumValues =
    response.data.paths?.["/control/{command}"]?.post?.parameters?.[0]?.schema?.enum ?? [];

  return enumValues.map((name) => ({
    name,
    requiresValue: name !== "start_regeneration",
  }));
}

export async function executeControlCommand(command: string, payload: ControlPayload): Promise<void> {
  await apiPost<ControlPayload, undefined>(`control/${command}`, payload);
}

export function useSoftenerSnapshotQuery() {
  return useQuery({
    queryFn: ({ signal }) => getSoftenerSnapshot(signal),
    queryKey: queryKeys.snapshot,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

export function useControlCommandsQuery() {
  return useQuery({
    queryFn: ({ signal }) => getControlCommands(signal),
    queryKey: queryKeys.commands,
    staleTime: 60_000,
  });
}

export function useControlMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ command, payload }: { command: string; payload: ControlPayload }) =>
      executeControlCommand(command, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.snapshot });
    },
  });
}
