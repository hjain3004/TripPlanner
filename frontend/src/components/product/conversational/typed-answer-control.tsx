"use client";

import { useId } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type {
  AnswerValue,
  ChoiceOption,
  ControlDefinition,
  MultiSelectControl,
  StructuredAnswerValue,
} from "./conversational-types";

interface TypedAnswerControlProps {
  control: ControlDefinition;
  value: AnswerValue;
  onChange: (value: AnswerValue) => void;
  disabled?: boolean;
  label: string;
  describedBy?: string;
}

const NO_PREFERENCE: ChoiceOption = {
  value: "no_preference",
  label: "No preference — choose for me",
  description: "I’ll keep this decision flexible.",
};

function structuredValue(value: AnswerValue): StructuredAnswerValue {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

function updateStructured(value: AnswerValue, key: string, next: string | number | boolean | string[] | number[]): StructuredAnswerValue {
  return { ...structuredValue(value), [key]: next };
}

function optionsWithDelegation(control: MultiSelectControl | Extract<ControlDefinition, { kind: "single-select" }>): ChoiceOption[] {
  if (!control.allowNoPreference || control.options.some((option) => option.value === NO_PREFERENCE.value)) {
    return control.options;
  }
  return [...control.options, NO_PREFERENCE];
}

function ChoiceCard({
  option,
  checked,
  type,
  name,
  onChange,
  disabled,
}: {
  option: ChoiceOption;
  checked: boolean;
  type: "radio" | "checkbox";
  name: string;
  onChange: () => void;
  disabled?: boolean;
}) {
  const shapeClass = type === "radio" ? "rounded-full" : "rounded-sm";
  /* token-lint-disable-next-line no-vendor-utilities -- peer focus ring is the accessible native-control state. */
  const markerClasses = "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center border-2 border-primary text-[11px] font-bold text-text-on-primary peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50";

  return (
    <label
      className={cn(
        "group flex min-h-[56px] cursor-pointer items-start gap-3 rounded-md border-2 px-4 py-3 transition-[background-color,border-color,transform] duration-180 ease-out motion-reduce:transition-none",
        checked ? "border-primary bg-accent-2 shadow-1" : "border-border bg-surface hover:border-primary/60",
        disabled ? "cursor-not-allowed opacity-50" : "",
      )}
    >
      <input
        className="peer sr-only"
        type={type}
        name={name}
        value={option.value}
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      <span
        aria-hidden="true"
        className={cn(
          markerClasses,
          shapeClass,
          checked ? "bg-primary" : "bg-surface",
        )}
      >
        {checked ? "✓" : null}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-text">{option.label}</span>
        {option.description ? <span className="mt-1 block text-xs leading-5 text-text-muted">{option.description}</span> : null}
      </span>
    </label>
  );
}

export function TypedAnswerControl({
  control,
  value,
  onChange,
  disabled = false,
  label,
  describedBy,
}: TypedAnswerControlProps) {
  const generatedId = useId();
  const inputId = `answer-${generatedId}`;
  const descriptionProps = describedBy ? { "aria-describedby": describedBy } : undefined;

  if (control.kind === "single-select") {
    const selected = typeof value === "string" ? value : "";
    return (
      <fieldset className="space-y-3" aria-label={label} {...descriptionProps}>
        <legend className="sr-only">{label}</legend>
        <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
          {optionsWithDelegation(control).map((option) => (
            <ChoiceCard
              key={option.value}
              option={option}
              checked={selected === option.value}
              type="radio"
              name={inputId}
              onChange={() => onChange(option.value)}
              disabled={disabled}
            />
          ))}
        </div>
      </fieldset>
    );
  }

  if (control.kind === "multi-select") {
    const selected = Array.isArray(value) ? value : [];
    const toggle = (option: ChoiceOption) => {
      if (option.value === NO_PREFERENCE.value) {
        onChange([NO_PREFERENCE.value]);
        return;
      }
      const next = selected.includes(option.value)
        ? selected.filter((item) => item !== option.value)
        : [...selected.filter((item) => item !== NO_PREFERENCE.value), option.value];
      if (control.maxSelections && next.length > control.maxSelections) return;
      onChange(next);
    };
    return (
      <fieldset className="space-y-3" aria-label={label} {...descriptionProps}>
        <legend className="sr-only">{label}</legend>
        <div className="grid gap-3 sm:grid-cols-2" role="group">
          {optionsWithDelegation(control).map((option) => (
            <ChoiceCard
              key={option.value}
              option={option}
              checked={selected.includes(option.value)}
              type="checkbox"
              name={inputId}
              onChange={() => toggle(option)}
              disabled={disabled}
            />
          ))}
        </div>
        {control.maxSelections ? (
          <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-muted">
            Choose up to {control.maxSelections}
          </p>
        ) : null}
      </fieldset>
    );
  }

  if (control.kind === "party") {
    const party = structuredValue(value);
    const selected = typeof party.purpose === "string" ? party.purpose : "";
    const children = Array.isArray(party.children_ages) ? party.children_ages.join(", ") : "";
    return (
      <fieldset className="space-y-4" aria-label={label} {...descriptionProps}>
        <legend className="sr-only">{label}</legend>
        <div className="grid gap-3 sm:grid-cols-2" role="radiogroup">
          {control.options.map((option) => (
            <ChoiceCard
              key={option.value}
              option={option}
              checked={selected === option.value}
              type="radio"
              name={inputId}
              onChange={() => onChange({
                ...structuredValue(value),
                purpose: option.value,
                adults: typeof party.adults === "number" && party.adults > 0 ? party.adults : control.defaultAdults,
                children_ages: Array.isArray(party.children_ages) ? party.children_ages : [],
              })}
              disabled={disabled}
            />
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor={`${inputId}-adults`} className="mb-2 block text-xs font-medium uppercase tracking-[0.06em] text-text-muted">Adults</label>
            <Input
              id={`${inputId}-adults`}
              type="number"
              min={1}
              max={20}
              value={typeof party.adults === "number" ? party.adults : control.defaultAdults}
              onChange={(event) => onChange(updateStructured(value, "adults", Number(event.target.value) || 1))}
              disabled={disabled}
              className="min-h-[48px] rounded-md bg-surface text-base"
            />
          </div>
          <div>
            <label htmlFor={`${inputId}-children`} className="mb-2 block text-xs font-medium uppercase tracking-[0.06em] text-text-muted">Children’s ages</label>
            <Input
              id={`${inputId}-children`}
              type="text"
              inputMode="numeric"
              placeholder="e.g. 4, 9"
              value={children}
              onChange={(event) => onChange(updateStructured(value, "children_ages", event.target.value.split(",").map((item) => Number(item.trim())).filter((age) => Number.isInteger(age) && age >= 0)))}
              disabled={disabled}
              className="min-h-[48px] rounded-md bg-surface text-base"
            />
          </div>
        </div>
      </fieldset>
    );
  }

  if (control.kind === "hard-constraints") {
    const constraints = structuredValue(value);
    const hasConstraints = constraints.has_constraints === true;
    const arrayField = (field: "dietary" | "accessibility" | "exclusions" | "immovable_events") => Array.isArray(constraints[field]) ? constraints[field].join(", ") : "";
    return (
      <fieldset className="space-y-4" aria-label={label} {...descriptionProps}>
        <legend className="sr-only">{label}</legend>
        <label className="flex min-h-[52px] cursor-pointer items-center gap-3 rounded-md border-2 border-border bg-surface px-4 py-3 text-sm font-semibold text-text">
          <input
            type="checkbox"
            checked={hasConstraints}
            onChange={(event) => onChange(updateStructured(value, "has_constraints", event.target.checked))}
            disabled={disabled}
            className="h-5 w-5 accent-primary"
          />
          I have requirements the plan must respect
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          {control.fields.filter((field) => field !== "has_constraints").map((field) => {
            const fieldLabel = field.replaceAll("_", " ");
            return (
              <div key={field}>
                <label htmlFor={`${inputId}-${field}`} className="mb-2 block text-xs font-medium uppercase tracking-[0.06em] text-text-muted">{fieldLabel}</label>
                <Input
                  id={`${inputId}-${field}`}
                  type="text"
                  value={arrayField(field)}
                  placeholder="Separate items with commas"
                  onChange={(event) => onChange(updateStructured(value, field, event.target.value.split(",").map((item) => item.trim()).filter(Boolean)))}
                  disabled={disabled || !hasConstraints}
                  className="min-h-[48px] rounded-md bg-surface text-base"
                />
              </div>
            );
          })}
        </div>
      </fieldset>
    );
  }

  if (control.kind === "trip-essentials") {
    const essentials = structuredValue(value);
    return (
      <fieldset className="grid gap-4 sm:grid-cols-2" aria-label={label} {...descriptionProps}>
        <legend className="sr-only">{label}</legend>
        {control.fields.map((field) => {
          const fieldLabel = field.replaceAll("_", " ");
          const fieldId = `${inputId}-${field}`;
          const numberField = field === "travelers" || field === "date_flexibility_days";
          return (
            <div key={field}>
              <label htmlFor={fieldId} className="mb-2 block text-xs font-medium uppercase tracking-[0.06em] text-text-muted">{fieldLabel}</label>
              <Input
                id={fieldId}
                type={field.includes("date") ? "date" : numberField ? "number" : "text"}
                min={numberField ? (field === "travelers" ? 1 : 0) : undefined}
                value={essentials[field] === undefined ? "" : String(essentials[field])}
                onChange={(event) => onChange(updateStructured(value, field, numberField ? Number(event.target.value) || 0 : event.target.value.toUpperCase()))}
                disabled={disabled}
                className="min-h-[48px] rounded-md bg-surface text-base"
              />
            </div>
          );
        })}
      </fieldset>
    );
  }

  if (control.kind === "slider") {
    const sliderValue = typeof value === "number" ? value : control.min;
    return (
      <div className="space-y-3">
        <label htmlFor={inputId} className="sr-only">{label}</label>
        <div className="flex items-center gap-3">
          <input
            id={inputId}
            className="h-3 min-h-[44px] w-full accent-primary"
            type="range"
            min={control.min}
            max={control.max}
            step={control.step ?? 1}
            value={sliderValue}
            onChange={(event) => onChange(Number(event.target.value))}
            disabled={disabled}
            {...descriptionProps}
          />
          <output className="min-w-[5rem] text-right font-mono text-sm font-semibold tabular-nums text-primary" htmlFor={inputId}>
            {sliderValue}{control.unit ? ` ${control.unit}` : ""}
          </output>
        </div>
        <div className="flex justify-between gap-4 text-xs text-text-muted" aria-hidden="true">
          <span>{control.minLabel ?? control.min}</span>
          <span>{control.maxLabel ?? control.max}</span>
        </div>
      </div>
    );
  }

  if (control.kind === "date") {
    return (
      <div>
        <label htmlFor={inputId} className="sr-only">{label}</label>
        <Input
          id={inputId}
          type="date"
          value={typeof value === "string" ? value : ""}
          min={control.min}
          max={control.max}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          {...descriptionProps}
          className="min-h-[48px] rounded-md bg-surface text-base"
        />
      </div>
    );
  }

  if (control.kind === "number") {
    return (
      <div className="flex items-center gap-3">
        <label htmlFor={inputId} className="sr-only">{label}</label>
        <Input
          id={inputId}
          type="number"
          inputMode="numeric"
          value={typeof value === "number" ? value : ""}
          min={control.min}
          max={control.max}
          step={control.step ?? 1}
          onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
          disabled={disabled}
          {...descriptionProps}
          className="min-h-[48px] max-w-[14rem] rounded-md bg-surface text-base"
        />
        {control.unit ? <span className="text-sm text-text-muted">{control.unit}</span> : null}
      </div>
    );
  }

  return (
    <div>
      <label htmlFor={inputId} className="sr-only">{label}</label>
      <Textarea
        id={inputId}
        value={typeof value === "string" ? value : ""}
        placeholder={control.placeholder}
        maxLength={control.maxLength}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        {...descriptionProps}
        className="min-h-[112px] rounded-md bg-surface text-base"
      />
      {control.maxLength ? (
        <p className="mt-2 text-right font-mono text-[10px] tabular-nums text-text-muted">
          {typeof value === "string" ? value.length : 0}/{control.maxLength}
        </p>
      ) : null}
    </div>
  );
}
