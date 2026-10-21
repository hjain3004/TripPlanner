"use client";

/**
 * The authenticated wallet surface (spec 17 §3-4, A3).
 *
 * Every number shown here comes from the server. This component performs no
 * reward arithmetic and keeps nothing in browser-side storage — the wallet lives
 * in the account, and the projection the optimizer will consume is derived
 * server-side and only rendered here.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type ApiFailure,
  balanceSummary,
  balancesFromInput,
  editedBalances,
  failureOf,
  isConflict,
  last4FromInput,
  nicknameOr,
  newClientEventId,
} from "@/components/product/wallet/wallet-policy";
import {
  type CardProductOut,
  type WalletEntryOut,
  apiClient,
  createWalletEntryAccountWalletPost,
  csrfHeaders,
  deleteWalletEntryAccountWalletEntryIdDelete,
  getCardProductsAccountCardProductsGet,
  getWalletAccountWalletGet,
  getWalletProjectionAccountWalletProjectionGet,
  meAuthMeGet,
  patchWalletEntryAccountWalletEntryIdPatch,
} from "@/lib/api";

export function WalletPanel() {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const me = useQuery({
    queryKey: ["auth-me"],
    retry: false,
    queryFn: async () => {
      const { data, error } = await meAuthMeGet({ client: apiClient });
      if (error) throw error;
      return data ?? null;
    },
  });
  const signedIn = me.isSuccess && me.data !== null;

  const wallet = useQuery({
    queryKey: ["wallet"],
    enabled: signedIn,
    queryFn: async () => {
      const { data, error } = await getWalletAccountWalletGet({ client: apiClient });
      if (error) throw error;
      return (data ?? []) as WalletEntryOut[];
    },
  });

  const projection = useQuery({
    queryKey: ["wallet-projection"],
    enabled: signedIn,
    queryFn: async () => {
      const { data, error } = await getWalletProjectionAccountWalletProjectionGet({
        client: apiClient,
      });
      if (error) throw error;
      return data ?? { card_ids: [], points_balances: {} };
    },
  });

  const products = useQuery({
    queryKey: ["card-products"],
    enabled: signedIn,
    queryFn: async () => {
      const { data, error } = await getCardProductsAccountCardProductsGet({
        client: apiClient,
      });
      if (error) throw error;
      return (data ?? []) as CardProductOut[];
    },
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["wallet"] });
    void queryClient.invalidateQueries({ queryKey: ["wallet-projection"] });
  }

  const addCard = useMutation({
    mutationFn: async (body: {
      card_id: string;
      nickname: string;
      last4: string | null;
      points_balances: Record<string, number>;
      client_event_id: string;
    }) => {
      const { data, error } = await createWalletEntryAccountWalletPost({
        client: apiClient,
        headers: csrfHeaders(),
        body,
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setFailure(null);
      refresh();
    },
    onError: (error) => setFailure(failureOf(error)),
  });

  const editCard = useMutation({
    mutationFn: async (vars: {
      entryId: string;
      expectedVersion: number;
      nickname: string;
      points_balances: Record<string, number>;
      clientEventId: string;
    }) => {
      const { data, error } = await patchWalletEntryAccountWalletEntryIdPatch({
        client: apiClient,
        headers: csrfHeaders(),
        path: { entry_id: vars.entryId },
        body: {
          expected_version: vars.expectedVersion,
          nickname: vars.nickname,
          points_balances: vars.points_balances,
          client_event_id: vars.clientEventId,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => {
      setFailure(null);
      setEditingId(null);
      refresh();
    },
    onError: (error) => setFailure(failureOf(error)),
  });

  const removeCard = useMutation({
    mutationFn: async (vars: { entryId: string; clientEventId: string }) => {
      const { error } = await deleteWalletEntryAccountWalletEntryIdDelete({
        client: apiClient,
        headers: csrfHeaders(),
        path: { entry_id: vars.entryId },
        query: { client_event_id: vars.clientEventId },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      setFailure(null);
      setConfirmingId(null);
      refresh();
    },
    onError: (error) => setFailure(failureOf(error)),
  });

  // --- signed out ---------------------------------------------------------- #
  if (me.isLoading) {
    return (
      <div data-testid="wallet-loading" className="flex flex-col gap-3">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (!signedIn) {
    return (
      <Alert data-testid="wallet-signed-out">
        <AlertTitle>Sign in to see your wallet</AlertTitle>
        <AlertDescription>
          Your cards and points balances are saved to your account.{" "}
          <Link href="/plan" className="border-b border-primary text-primary">
            Sign in to continue
          </Link>
        </AlertDescription>
      </Alert>
    );
  }

  const entries = wallet.data ?? [];
  const conflict = isConflict(failure);

  return (
    <div className="flex flex-col gap-8">
      <p data-testid="wallet-privacy-note" className="text-[13px] text-text-muted">
        TripPlanner stores the <strong>card product</strong> you hold and, if you
        choose, the last four digits so you can tell two cards apart. It never
        stores a full card number, expiry date, CVV, PIN, or any banking login.
      </p>

      {failure !== null && (
        <Alert
          data-testid={conflict ? "wallet-conflict" : "wallet-error"}
          variant="destructive"
        >
          <AlertTitle>
            {conflict ? "This wallet changed elsewhere" : "That didn't work"}
          </AlertTitle>
          <AlertDescription>
            {failure.message}
            {conflict && (
              <>
                {" "}
                <Button
                  data-testid="wallet-reload"
                  variant="link"
                  onClick={() => {
                    setFailure(null);
                    refresh();
                  }}
                >
                  Reload the current version
                </Button>
              </>
            )}
          </AlertDescription>
        </Alert>
      )}

      {wallet.isError && (
        <Alert data-testid="wallet-load-error" variant="destructive">
          <AlertTitle>Your wallet could not be loaded</AlertTitle>
          <AlertDescription>
            <Button data-testid="wallet-retry" onClick={() => void wallet.refetch()}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* --- stored cards --- */}
      <section aria-labelledby="wallet-cards-heading" className="flex flex-col gap-4">
        <h2 id="wallet-cards-heading" className="text-[18px] font-semibold text-text">
          Your cards
        </h2>

        {wallet.isLoading ? (
          <Skeleton data-testid="wallet-list-loading" className="h-24 w-full" />
        ) : entries.length === 0 ? (
          <p data-testid="wallet-empty" className="text-[14px] text-text-muted">
            You have no cards saved yet. Add one below and planning will use it.
          </p>
        ) : (
          <ul data-testid="wallet-list" className="flex flex-col gap-3">
            {entries.map((entry) => (
              <li
                key={entry.id}
                data-testid="wallet-entry"
                className="border border-border p-4 flex flex-col gap-2"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[15px] font-semibold text-text">
                    {entry.nickname}
                  </span>
                  <span className="text-[12px] text-text-muted">
                    {entry.card_id}
                    {entry.last4 !== null ? ` · ends ${entry.last4}` : ""}
                  </span>
                </div>
                <span className="text-[13px] text-text-muted">
                  {balanceSummary(entry.points_balances)}
                </span>

                <div className="flex gap-3">
                  <Button
                    data-testid={`wallet-edit-${entry.id}`}
                    onClick={() =>
                      setEditingId(editingId === entry.id ? null : entry.id)
                    }
                    aria-expanded={editingId === entry.id}
                  >
                    Edit
                  </Button>
                  <Button
                    data-testid={`wallet-remove-${entry.id}`}
                    variant="destructive"
                    onClick={() => setConfirmingId(entry.id)}
                  >
                    Remove
                  </Button>
                </div>

                {confirmingId === entry.id && (
                  <div
                    data-testid="wallet-remove-confirm"
                    role="alertdialog"
                    aria-label={`Remove ${entry.nickname}?`}
                    className="border border-border p-3 flex flex-col gap-2"
                  >
                    <p className="text-[13px] text-text">
                      Remove {entry.nickname}? Planning will stop using this card.
                    </p>
                    <div className="flex gap-3">
                      <Button
                        data-testid="wallet-remove-confirm-yes"
                        variant="destructive"
                        disabled={removeCard.isPending}
                        onClick={() =>
                          removeCard.mutate({
                            entryId: entry.id,
                            clientEventId: newClientEventId(),
                          })
                        }
                      >
                        Yes, remove it
                      </Button>
                      <Button
                        data-testid="wallet-remove-confirm-no"
                        onClick={() => setConfirmingId(null)}
                      >
                        Keep it
                      </Button>
                    </div>
                  </div>
                )}

                {editingId === entry.id && (
                  <EditCardForm
                    entry={entry}
                    pending={editCard.isPending}
                    onCancel={() => setEditingId(null)}
                    onSubmit={(nickname, balances) =>
                      editCard.mutate({
                        entryId: entry.id,
                        expectedVersion: entry.version,
                        nickname,
                        points_balances: balances,
                        clientEventId: newClientEventId(),
                      })
                    }
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* --- add a card --- */}
      <AddCardForm
        products={products.data ?? []}
        loading={products.isLoading}
        error={products.isError}
        onRetry={() => void products.refetch()}
        pending={addCard.isPending}
        onSubmit={(body) => addCard.mutate(body)}
      />

      {/* --- what planning will use --- */}
      <section
        aria-labelledby="wallet-projection-heading"
        className="flex flex-col gap-2 border-t border-border pt-5"
      >
        <h2
          id="wallet-projection-heading"
          className="text-[18px] font-semibold text-text"
        >
          What planning will use
        </h2>
        {projection.isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : projection.isError ? (
          <Alert data-testid="wallet-projection-error" variant="destructive">
            <AlertTitle>Planning wallet could not be loaded</AlertTitle>
            <AlertDescription>
              The saved wallet could not be confirmed. Retry before planning so the
              wallet summary is not mistaken for a cash-only result.
              <Button
                data-testid="wallet-projection-retry"
                onClick={() => void projection.refetch()}
              >
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <div data-testid="wallet-projection" className="text-[13px] text-text-muted">
            {(projection.data?.card_ids.length ?? 0) === 0 ? (
              <span data-testid="wallet-projection-empty">
                No cards saved, so planning will price this trip as cash only.
              </span>
            ) : (
              <>
                <span data-testid="wallet-projection-cards">
                  Cards: {projection.data?.card_ids.join(", ")}
                </span>
                <br />
                <span data-testid="wallet-projection-points">
                  Points: {balanceSummary(projection.data?.points_balances ?? {})}
                </span>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function AddCardForm({
  products,
  loading,
  error,
  onRetry,
  pending,
  onSubmit,
}: {
  products: CardProductOut[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  pending: boolean;
  onSubmit: (body: {
    card_id: string;
    nickname: string;
    last4: string | null;
    points_balances: Record<string, number>;
    client_event_id: string;
  }) => void;
}) {
  const [cardId, setCardId] = useState("");
  const [nickname, setNickname] = useState("");
  const [last4, setLast4] = useState("");
  const [currency, setCurrency] = useState("");
  const [amount, setAmount] = useState("");

  const eligible = products.filter((p) => p.is_eligible);

  return (
    <section aria-labelledby="wallet-add-heading" className="flex flex-col gap-4">
      <h2 id="wallet-add-heading" className="text-[18px] font-semibold text-text">
        Add a card
      </h2>

      {loading ? (
        <Skeleton className="h-10 w-full" />
      ) : error ? (
        <Alert data-testid="wallet-products-error" variant="destructive">
          <AlertTitle>Card products could not be loaded</AlertTitle>
          <AlertDescription>
            Approved card products are unavailable, so a card cannot be added safely.
            <Button data-testid="wallet-products-retry" onClick={onRetry}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <form
          data-testid="wallet-add-form"
          className="flex flex-col gap-3 max-w-[520px]"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({
              card_id: cardId,
              nickname: nicknameOr(nickname, "My card"),
              last4: last4FromInput(last4),
              points_balances: balancesFromInput(currency, amount),
              client_event_id: newClientEventId(),
            });
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="wallet-card-product">Card product</Label>
            {/* A native select keeps the approved-product list keyboard-operable
                and screen-reader friendly without extra ARIA wiring. */}
            <select
              id="wallet-card-product"
              data-testid="wallet-card-product"
              required
              value={cardId}
              onChange={(event) => setCardId(event.target.value)}
              className="border border-border bg-surface text-text p-2 text-[14px]"
            >
              <option value="">Choose a card product…</option>
              {eligible.map((product) => (
                <option key={product.card_id} value={product.card_id}>
                  {product.issuer} — {product.display_name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="wallet-nickname">Nickname</Label>
            <Input
              id="wallet-nickname"
              data-testid="wallet-nickname"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              placeholder="Everyday card"
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="wallet-last4">Last four digits (optional)</Label>
            <Input
              id="wallet-last4"
              data-testid="wallet-last4"
              inputMode="numeric"
              maxLength={4}
              value={last4}
              onChange={(event) => setLast4(event.target.value)}
              aria-describedby="wallet-last4-help"
            />
            <span id="wallet-last4-help" className="text-[12px] text-text-muted">
              Four digits only, to tell two cards of the same product apart.
            </span>
          </div>

          <fieldset className="flex flex-col gap-1 border-0 p-0">
            <legend className="text-[13px] text-text-muted">
              Points balance (optional)
            </legend>
            <div className="flex gap-2">
              <Input
                aria-label="Points currency"
                data-testid="wallet-points-currency"
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
                placeholder="hdfc-reward-points"
              />
              <Input
                aria-label="Points amount"
                data-testid="wallet-points-amount"
                inputMode="numeric"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0"
              />
            </div>
          </fieldset>

          <Button data-testid="wallet-add-submit" type="submit" disabled={pending}>
            {pending ? "Adding…" : "Add card"}
          </Button>
        </form>
      )}
    </section>
  );
}

function EditCardForm({
  entry,
  pending,
  onCancel,
  onSubmit,
}: {
  entry: WalletEntryOut;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (nickname: string, balances: Record<string, number>) => void;
}) {
  const firstCurrency = Object.keys(entry.points_balances)[0] ?? "";
  const [nickname, setNickname] = useState(entry.nickname);
  const [currency, setCurrency] = useState(firstCurrency);
  const [amount, setAmount] = useState(
    firstCurrency === "" ? "" : String(entry.points_balances[firstCurrency] ?? ""),
  );

  return (
    <form
      data-testid="wallet-edit-form"
      className="border border-border p-3 flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(
          nicknameOr(nickname, entry.nickname),
          editedBalances(entry.points_balances, firstCurrency, currency, amount),
        );
      }}
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor={`wallet-edit-nickname-${entry.id}`}>Nickname</Label>
        <Input
          id={`wallet-edit-nickname-${entry.id}`}
          data-testid="wallet-edit-nickname"
          value={nickname}
          onChange={(event) => setNickname(event.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Input
          aria-label="Points currency"
          data-testid="wallet-edit-currency"
          value={currency}
          onChange={(event) => setCurrency(event.target.value)}
        />
        <Input
          aria-label="Points amount"
          data-testid="wallet-edit-amount"
          inputMode="numeric"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
      </div>
      <div className="flex gap-3">
        <Button data-testid="wallet-edit-save" type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save changes"}
        </Button>
        <Button data-testid="wallet-edit-cancel" type="button" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
