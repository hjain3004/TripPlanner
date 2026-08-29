"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export type PreferenceConfirmationAction = "reset" | "remove";

interface PreferenceConfirmationDialogProps {
  action: PreferenceConfirmationAction | null;
  groupTitle: string;
  onCancel: () => void;
  onConfirm: () => void;
}

const ACTION_COPY: Record<
  PreferenceConfirmationAction,
  { title: string; description: string; confirm: string }
> = {
  reset: {
    title: "Reset saved preferences?",
    description:
      "This restores the group to TripPlanner defaults. Your trip answers stay unchanged.",
    confirm: "Reset preferences",
  },
  remove: {
    title: "Remove saved preferences?",
    description:
      "This removes the saved group from your profile. It cannot be undone, but you can add it again later.",
    confirm: "Remove preferences",
  },
};

export function PreferenceConfirmationDialog({
  action,
  groupTitle,
  onCancel,
  onConfirm,
}: PreferenceConfirmationDialogProps) {
  const copy = action ? ACTION_COPY[action] : null;

  return (
    <Dialog
      open={action !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      {copy && (
        <DialogContent aria-describedby="preference-confirmation-description">
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription id="preference-confirmation-description">
              {groupTitle}. {copy.description}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="sm:justify-end">
            <Button type="button" variant="outline" className="min-h-11" onClick={onCancel}>
              Keep as is
            </Button>
            <Button
              type="button"
              variant={action === "remove" ? "destructive" : "default"}
              className="min-h-11"
              onClick={onConfirm}
            >
              {copy.confirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}
