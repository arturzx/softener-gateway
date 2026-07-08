import { Alert } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

import { errorMessage } from "../utils/format";

type ErrorStateProps = {
  error: unknown;
};

export function ErrorState({ error }: ErrorStateProps) {
  return (
    <Alert color="red" icon={<IconAlertTriangle size={18} />} radius="lg" variant="light">
      Could not load data from the API: {errorMessage(error)}
    </Alert>
  );
}
