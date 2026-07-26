"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Progress } from "@/components/ui/progress";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { RouteSpine } from "@/components/product/route-spine";
import { DecisionLedger } from "@/components/product/decision-ledger";
import { MoneyText } from "@/components/product/money-text";
import { ProvenanceBand } from "@/components/product/provenance-band";
import { TrustChip } from "@/components/product/trust-chip";
import { WhyThis } from "@/components/product/why-this";
import { NotchLabel } from "@/components/product/notch-label";

export default function KitchenSink() {
  return (
    <div className="min-h-screen bg-canvas font-ui text-text">
      <div className="mx-auto max-w-4xl px-6 py-12">

        {/* ───── Type Scale ───── */}
        <section className="mb-16">
          <h1 className="font-display text-5xl leading-tight text-text">Bodoni Moda Display</h1>
          <h2 className="font-display text-3xl leading-snug text-text mt-6">Section Heading (h2)</h2>
          <h3 className="font-display text-xl leading-snug text-text mt-4">Card / Panel Title (h3)</h3>
          <p className="text-base leading-relaxed text-text mt-4">
            Body text set in Schibsted Grotesk at 1rem / 1.625 line-height. This is the primary
            reading face for all product copy, descriptions, and explanatory text.
          </p>
          <p className="text-sm leading-relaxed text-text-muted mt-3">
            Supporting text in Schibsted Grotesk 0.875rem. Used for secondary information and
            metadata labels.
          </p>
          <p className="text-xs leading-relaxed text-text-faint mt-3 font-mono">
            Metadata text in Roboto Mono 0.75rem. For data, stats, and provenance bands.
          </p>
        </section>

        <Separator className="my-16" />

        {/* ───── Palette & Contrast Pairs ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Palette</h2>
          <div className="grid grid-cols-5 gap-3">
            {[
              { name: "canvas", class: "bg-canvas border" },
              { name: "surface", class: "bg-surface" },
              { name: "elevated", class: "bg-elevated shadow-sm" },
              { name: "primary", class: "bg-primary" },
              { name: "accent-1", class: "bg-accent-1" },
              { name: "accent-2", class: "bg-accent-2" },
              { name: "accent-3", class: "bg-accent-3" },
              { name: "accent-4", class: "bg-accent-4" },
              { name: "success", class: "bg-success" },
              { name: "warning", class: "bg-warning" },
            ].map((c) => (
              <div key={c.name} className={`h-16 rounded-sm ${c.class}`}>
                <span className="text-[10px] text-text-muted block p-1">{c.name}</span>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-6 mt-6">
            <div className="bg-bg border border-border p-4 rounded-sm">
              <span className="text-sm text-text">Text on bg</span>
              <span className="text-sm text-text-muted ml-4">Muted</span>
              <span className="text-sm text-text-faint ml-4">Faint</span>
            </div>
            <div className="bg-primary text-primary-text p-4 rounded-sm">
              <span className="text-sm">Primary on primary</span>
            </div>
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Surfaces & Elevation ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Surfaces</h2>
          <div className="grid grid-cols-3 gap-4">
            <Card className="p-4">
              <p className="text-sm font-medium">Card / Elevated</p>
              <p className="text-xs text-text-muted mt-1">Default card surface</p>
            </Card>
            <div className="border border-border rounded-sm p-4">
              <p className="text-sm font-medium">Bordered Surface</p>
              <p className="text-xs text-text-muted mt-1">border-border</p>
            </div>
            <div className="bg-canvas border border-border rounded-sm p-4">
              <p className="text-sm font-medium">Canvas</p>
              <p className="text-xs text-text-muted mt-1">Page canvas</p>
            </div>
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Buttons & Fields ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Buttons &amp; Fields</h2>
          <div className="flex flex-wrap gap-3 items-center">
            <Button>Default</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="destructive">Destructive</Button>
            <Button disabled>Disabled</Button>
          </div>
          <div className="grid grid-cols-2 gap-4 mt-6">
            <div className="space-y-2">
              <Label htmlFor="input-demo">Label</Label>
              <Input id="input-demo" placeholder="Input placeholder" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="textarea-demo">Textarea</Label>
              <Textarea id="textarea-demo" placeholder="Textarea placeholder" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="select-demo">Select</Label>
              <Select>
                <SelectTrigger id="select-demo"><SelectValue placeholder="Choose..." /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">Option one</SelectItem>
                  <SelectItem value="2">Option two</SelectItem>
                  <SelectItem value="3">Option three</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Progress</Label>
              <Progress value={65} className="mt-3" aria-label="Loading progress" />
            </div>
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Badges & Provenance ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Badges &amp; Provenance</h2>
          <div className="flex flex-wrap gap-2">
            <Badge>Default</Badge>
            <Badge variant="secondary">Secondary</Badge>
            <Badge variant="outline">Outline</Badge>
            <Badge variant="destructive">Destructive</Badge>
          </div>
          <div className="flex flex-wrap gap-2 mt-4">
            <TrustChip variant="verified" label="Verified" />
            <TrustChip variant="warning" label="Review Required" />
            <TrustChip variant="needs-verification" label="Needs Verification" />
          </div>
          <div className="mt-4">
            <ProvenanceBand
              sourceUrl="https://example.com/airline/tariff"
              lastVerified="2026-07-25"
              verifiedBy="Agent"
              confidence="0.92"
            />
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Route / Wayfinding ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Route Spine</h2>
          <RouteSpine
            steps={[
              { id: "1", state: "done", label: "Departure: BLR" },
              { id: "2", state: "current", label: "Layover: SIN" },
              { id: "3", state: "pending", label: "Arrival: KUL" },
              { id: "4", state: "warning", label: "Visa Check", content: <span className="text-xs text-accent-4">Visa required — review needed</span> },
            ]}
          />
        </section>

        <Separator className="my-16" />

        {/* ───── Numeric Alignment / Decision Ledger ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Decision Ledger</h2>
          <DecisionLedger
            title="Cost Breakdown"
            items={[
              { id: "a", label: "Base Fare", value: "₹24,500" },
              { id: "b", label: "Taxes & Surcharges", value: "₹4,200" },
              { id: "c", label: "Card Discount", value: "-₹1,800" },
              { id: "d", label: "Total", value: "₹26,900", dominant: true, notch: "BEST" },
            ]}
          />
          <div className="mt-6">
            <p className="text-sm text-text-muted mb-2">MoneyText examples (tabular-nums):</p>
            <div className="space-y-1">
              <p><span className="text-text-muted w-32 inline-block">24,500 INR:</span> <MoneyText minor={2450000} /></p>
              <p><span className="text-text-muted w-32 inline-block">1,234 USD:</span> <MoneyText minor={123400} currency="USD" /></p>
              <p><span className="text-text-muted w-32 inline-block">Points:</span> <span className="tabular-nums">45,000</span></p>
            </div>
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Disclosure (Accordion + WhyThis) ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Disclosure</h2>
          <Accordion type="single" collapsible className="w-full">
            <AccordionItem value="1">
              <AccordionTrigger>Accordion Item One</AccordionTrigger>
              <AccordionContent>
                This is the content of the first accordion panel. It reveals on click.
              </AccordionContent>
            </AccordionItem>
            <AccordionItem value="2">
              <AccordionTrigger>Accordion Item Two</AccordionTrigger>
              <AccordionContent>
                A second panel. Multiple panels can be open when type is &ldquo;multiple&rdquo;.
              </AccordionContent>
            </AccordionItem>
          </Accordion>
          <div className="mt-6 border border-border rounded-sm px-4">
            <NotchLabel className="mb-2">INSIGHT</NotchLabel>
            <p className="text-sm text-text pb-2">
              A notch label interrupts a ruled surface to call out a key insight.
            </p>
            <WhyThis summary="Why this recommendation?">
              <p>This option minimizes total cost while maximizing points earn rate given the selected cards.</p>
            </WhyThis>
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Dialog / Sheet / Tooltip ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Overlays</h2>
          <div className="flex flex-wrap gap-3">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline">Open Dialog</Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Confirm Booking</DialogTitle>
                  <DialogDescription>
                    This action will reserve your selected itinerary. Review the details before continuing.
                  </DialogDescription>
                </DialogHeader>
                <div className="flex justify-end gap-2 mt-4">
                  <Button variant="outline">Cancel</Button>
                  <Button>Confirm</Button>
                </div>
              </DialogContent>
            </Dialog>

            <Sheet>
              <SheetTrigger asChild>
                <Button variant="outline">Open Sheet</Button>
              </SheetTrigger>
              <SheetContent>
                <SheetHeader>
                  <SheetTitle>Details</SheetTitle>
                  <SheetDescription>
                    Additional information about the selected option.
                  </SheetDescription>
                </SheetHeader>
                <div className="mt-4 space-y-3">
                  <p className="text-sm text-text">Flight: 6E 401</p>
                  <p className="text-sm text-text-muted">BLR → SIN, 14 Nov 2026</p>
                  <p className="text-sm text-text-muted">Economy, 1 adult</p>
                </div>
              </SheetContent>
            </Sheet>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline">Hover for Tooltip</Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>This is a tooltip with additional context.</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </section>

        <Separator className="my-16" />

        {/* ───── Tabs ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Tabs</h2>
          <Tabs defaultValue="flights">
            <TabsList>
              <TabsTrigger value="flights">Flights</TabsTrigger>
              <TabsTrigger value="hotels">Hotels</TabsTrigger>
              <TabsTrigger value="cards">Cards</TabsTrigger>
            </TabsList>
            <TabsContent value="flights" className="p-4 text-sm text-text">
              Flight options and availability.
            </TabsContent>
            <TabsContent value="hotels" className="p-4 text-sm text-text">
              Hotel recommendations and pricing.
            </TabsContent>
            <TabsContent value="cards" className="p-4 text-sm text-text">
              Credit card optimization and rewards.
            </TabsContent>
          </Tabs>
        </section>

        <Separator className="my-16" />

        {/* ───── Loading & Error States ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Loading &amp; Error States</h2>
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-16" />
            </div>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
          <Alert variant="destructive" className="mt-4">
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>
              Something went wrong while searching for flights. Please try again.
            </AlertDescription>
          </Alert>
          <Alert variant="default" className="mt-2">
            <AlertTitle>Info</AlertTitle>
            <AlertDescription>
              Your session will expire in 10 minutes.
            </AlertDescription>
          </Alert>
        </section>

        <Separator className="my-16" />

        {/* ───── Nested Theme Proof ───── */}
        <section className="mb-16">
          <h2 className="font-display text-3xl mb-6">Nested Theme Proof</h2>
          <div className="bg-bg border border-border rounded-sm p-6">
            <p className="text-sm text-text-muted mb-2">Default (Singapore):</p>
            <p className="text-lg text-text">Primary text color in Singapore theme</p>
            <Button className="mt-2">Singapore Button</Button>
          </div>
          <div className="theme-singapore bg-bg border border-border rounded-sm p-6 mt-4">
            {/* token-lint-disable-next-line no-color-literals -- deliberate nested-theme override proof */}
            <div className="[--color-primary:oklch(0.45_0.12_280)] [--color-bg:oklch(0.98_0.02_280)] [--color-primary-foreground:oklch(0.98_0.02_280)]">
              <p className="text-sm text-text-muted mb-2">Nested override (purple tint):</p>
              {/* token-lint-disable-next-line no-color-literals -- inline style for override demo */}
              <p className="text-lg" style={{ color: "oklch(0.45 0.12 280)" }}>
                This text uses the override primary
              </p>
              {/* token-lint-disable-next-line no-color-literals -- inline style for override demo */}
              <Button className="mt-2" style={{ backgroundColor: "oklch(0.45 0.12 280)" }}>
                Override Button
              </Button>
            </div>
          </div>
        </section>

      </div>
    </div>
  );
}
