/**
 * Systematic Prediction Challenge: get a prompt right before it is submitted.
 *
 * BRAIN has no public API for submitting one, so the submission itself stays on BRAIN's form.
 * What happens here is everything that can be settled beforehand — BRAIN's own structural rules,
 * the mistakes that silently cost PnL, whether the prompt gives the same answer twice — and the
 * seven form values, ready to copy in the order the form asks for them.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckIcon,
  CircleAlertIcon,
  ClipboardCheckIcon,
  CopyIcon,
  ExternalLinkIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/http'
import { cn } from '@/lib/cn'
import { fmt } from '@/lib/format'
import { useDebounced } from '@/lib/use-debounced'
import {
  Badge,
  Button,
  Disclosure,
  Empty,
  ErrorNotice,
  Field,
  Input,
  LINK,
  Metric,
  Notice,
  Page,
  PageHeader,
  Panel,
  Skeleton,
  Textarea,
} from '@/ui/kit'
import { Confirm, Select } from '@/ui/overlay'
import { type Draft, type Form, type Issue, type Report, spc } from './api'
import { PROMPT_TEMPLATE } from './template'

const BRAIN_URL = 'https://platform.worldquantbrain.com/competitions'
const BLANK: Form = {
  name: '',
  prompt: '',
  model: 'Claude',
  model_version: '',
  frequency: 'Daily',
  weight: 0.3,
  sample_output: '',
}

const toForm = (d: Draft): Form => ({
  name: d.name,
  prompt: d.prompt,
  model: d.model,
  model_version: d.modelVersion,
  frequency: d.frequency,
  weight: d.weight,
  sample_output: d.sampleOutput,
})

const touched = (f: Form) => Boolean(f.prompt.trim() || f.sample_output.trim() || f.name.trim())

function IssueRow({ issue }: { issue: Issue }) {
  const Icon = issue.level === 'error' ? CircleAlertIcon : TriangleAlertIcon
  return (
    <li className="flex gap-2 text-body">
      {issue.level === 'info' ? (
        <CheckIcon className="mt-0.5 size-4 shrink-0 text-ink-subtle" aria-hidden />
      ) : (
        <Icon
          aria-hidden
          className={cn(
            'mt-0.5 size-4 shrink-0',
            issue.level === 'error' ? 'text-pnl-negative-text' : 'text-status-warning',
          )}
        />
      )}
      <span className="min-w-0 text-pretty break-words text-ink-muted">
        <span className="sr-only">{issue.level}: </span>
        {issue.message}
      </span>
    </li>
  )
}

function Checks({ report, pending }: { report: Report | undefined; pending: boolean }) {
  if (!report) {
    return pending ? (
      <Skeleton className="h-40" label="Checking the prompt" />
    ) : (
      <Empty icon={<ClipboardCheckIcon />} title="Nothing to check yet">
        Fill in the form, or start from the template, and the checks appear here as you type.
      </Empty>
    )
  }
  const errors = report.issues.filter((i) => i.level === 'error')
  const warnings = report.issues.filter((i) => i.level === 'warning')
  const info = report.issues.filter((i) => i.level === 'info')
  const { stats, stability } = report
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={report.ready ? 'profit' : 'loss'}>
          {report.ready ? 'Ready to submit' : `${fmt.int(errors.length)} to fix`}
        </Badge>
        {warnings.length > 0 && (
          <Badge tone="warn">
            {fmt.int(warnings.length)} warning{warnings.length === 1 ? '' : 's'}
          </Badge>
        )}
        {pending && <span className="text-body-compact text-ink-subtle">Checking…</span>}
      </div>
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric boxed size="sm" label="Names" value={fmt.int(stats.count)} />
          <Metric boxed size="sm" label="Long / short" value={`${stats.long} / ${stats.short}`} />
          <Metric boxed size="sm" label="Gross" value={fmt.ratio(stats.gross)} />
          <Metric
            boxed
            size="sm"
            label="Median horizon"
            value={stats.medianHorizon ? `${stats.medianHorizon}d` : '—'}
          />
        </div>
      )}
      {stability && (
        <p className="text-body-compact text-ink-subtle">
          {stability.identical
            ? `${stability.runs} runs compared: identical.`
            : `${stability.runs} runs compared: ${fmt.pct(stability.minOverlap, 0)} of names in common at worst; ${stability.unstableNames.length} name(s) not in every run.`}
        </p>
      )}
      {[errors, warnings, info].map(
        (group) =>
          group.length > 0 && (
            <ul key={group[0]?.level} className="flex flex-col gap-2">
              {group.map((issue) => (
                <IssueRow key={`${issue.code}-${issue.message}`} issue={issue} />
              ))}
            </ul>
          ),
      )}
      {report.overlaps.length > 0 && (
        <p className="text-body-compact text-ink-subtle">
          Overlap with saved prompts:{' '}
          {report.overlaps
            .map((o) => `${o.name || 'Untitled'} ${fmt.pct(o.overlap, 0)} (${o.shared} names)`)
            .join(', ')}
        </p>
      )}
    </div>
  )
}

function CopyRow({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      toast.success(`Copied ${label}`)
    } catch {
      toast.error(`Could not copy ${label}`, { description: 'Select the text and copy it.' })
    }
  }
  return (
    <li className="flex items-start gap-3 border-b border-hairline py-2 last:border-0">
      <span className="w-32 shrink-0 pt-1 text-caption font-medium text-ink-muted">{label}</span>
      <span
        className={cn(
          'num min-w-0 flex-1 pt-1 text-body-compact text-ink-subtle break-words',
          wide && 'line-clamp-2',
        )}
      >
        {value || '—'}
      </span>
      <Button size="sm" variant="ghost" disabled={!value} onClick={copy}>
        <CopyIcon aria-hidden />
        Copy
      </Button>
    </li>
  )
}

export function SpcScreen() {
  const client = useQueryClient()
  const saved = useQuery({ queryKey: ['spc', 'drafts'], queryFn: spc.drafts })
  const [form, setForm] = useState<Form>(BLANK)
  const [runs, setRuns] = useState<string[]>([])
  const [draftId, setDraftId] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState<Draft | null>(null)
  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const settled = useDebounced({ form, runs, draftId }, 500)
  const report = useQuery({
    queryKey: ['spc', 'validate', settled],
    queryFn: () => spc.validate(settled.form, settled.runs.filter(Boolean), settled.draftId),
    enabled: touched(settled.form),
    placeholderData: (previous) => previous,
  })

  const refresh = () => client.invalidateQueries({ queryKey: ['spc', 'drafts'] })
  const save = useMutation({
    mutationFn: () => (draftId ? spc.update(draftId, form) : spc.create(form)),
    onSuccess: (d) => {
      setDraftId(d.id)
      toast.success('Saved')
      refresh()
    },
  })
  const mark = useMutation({
    mutationFn: async () => {
      const d = draftId ? await spc.update(draftId, form) : await spc.create(form)
      return spc.mark(d.id, true)
    },
    onSuccess: (d) => {
      setDraftId(d.id)
      setConfirming(false)
      toast.success('Recorded as submitted')
      refresh()
    },
  })
  const unmark = useMutation({
    mutationFn: (d: Draft) => spc.mark(d.id, false),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (d: Draft) => spc.remove(d.id),
    onSuccess: (_, d) => {
      if (d.id === draftId) {
        setDraftId(null)
        setForm(BLANK)
        setRuns([])
      }
      setDeleting(null)
      refresh()
    },
  })

  const load = (d: Draft) => {
    setDraftId(d.id)
    setForm(toForm(d))
    setRuns([])
  }
  const fresh = () => {
    setDraftId(null)
    setForm(BLANK)
    setRuns([])
  }
  const ready = report.data?.ready === true && touched(form)
  const meta = saved.data
  const limits = meta?.limits

  return (
    <Page>
      <PageHeader
        title="SPC Submission"
        description="Check a Systematic Prediction Challenge prompt against BRAIN's rules, then copy its fields into BRAIN's form. BRAIN has no way to submit one from here."
        actions={
          <Button size="sm" onClick={fresh}>
            New prompt
          </Button>
        }
      />

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel
          title="Prompt"
          description={draftId ? 'Editing a saved prompt.' : 'Not saved yet.'}
          actions={
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => set('prompt', PROMPT_TEMPLATE)}
                disabled={form.prompt.trim().length > 0}
              >
                Start from template
              </Button>
              <Button
                size="sm"
                loading={save.isPending}
                disabled={!touched(form)}
                onClick={() => save.mutate()}
              >
                Save
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-4">
            <Field label="Prompt name" hint='A label, e.g. "FCF Quality Screen".'>
              <Input value={form.name} onChange={(e) => set('name', e.target.value)} />
            </Field>
            <Field
              label="Prompt text"
              hint={`${fmt.int(form.prompt.length)} of 10,000 characters. Your thesis, in any language.`}
              error={form.prompt.length > 10_000 ? 'Over the 10,000 character limit.' : undefined}
            >
              <Textarea
                className="min-h-56 font-mono"
                value={form.prompt}
                aria-invalid={form.prompt.length > 10_000}
                onChange={(e) => set('prompt', e.target.value)}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Model" hint="The one you tested with.">
                <Select
                  label="Model"
                  className="w-full"
                  value={form.model}
                  onChange={(v) => set('model', v)}
                  items={(meta?.models ?? [form.model]).map((m) => ({ value: m, label: m }))}
                />
              </Field>
              <Field label="Model version" hint="Optional. Copy it from the provider, e.g. 5.5.">
                <Input
                  value={form.model_version}
                  onChange={(e) => set('model_version', e.target.value)}
                />
              </Field>
              <Field label="Update frequency">
                <Select
                  label="Update frequency"
                  className="w-full"
                  value={form.frequency}
                  onChange={(v) => set('frequency', v)}
                  items={(meta?.frequencies ?? [form.frequency]).map((m) => ({
                    value: m,
                    label: m,
                  }))}
                />
              </Field>
              <Field label="Weight" hint="0 to 1, two decimals. 0 means the prompt does not run.">
                <Input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={form.weight}
                  onChange={(e) => set('weight', e.target.valueAsNumber)}
                />
              </Field>
            </div>
            <Field
              label="Sample output"
              hint="Paste exactly what your final run produced, not a template."
            >
              <Textarea
                className="min-h-56 font-mono"
                value={form.sample_output}
                onChange={(e) => set('sample_output', e.target.value)}
              />
            </Field>
            <Disclosure summary={`Fresh-chat re-runs (${runs.length})`}>
              <div className="flex flex-col gap-3">
                <p className="text-body-compact text-ink-subtle">
                  Run the finished prompt again in a new, empty conversation and paste each result.
                  The checks then say whether it gave the same book.
                </p>
                {runs.map((run, i) => (
                  <Field key={`run-${i + 2}`} label={`Run ${i + 2}`}>
                    <Textarea
                      className="min-h-32 font-mono"
                      value={run}
                      onChange={(e) =>
                        setRuns((all) => all.map((r, j) => (j === i ? e.target.value : r)))
                      }
                    />
                  </Field>
                ))}
                <div className="flex gap-2">
                  {runs.length < 4 && (
                    <Button size="sm" onClick={() => setRuns((all) => [...all, ''])}>
                      Add a run
                    </Button>
                  )}
                  {runs.length > 0 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setRuns((all) => all.slice(0, -1))}
                    >
                      Remove the last
                    </Button>
                  )}
                </div>
              </div>
            </Disclosure>
          </div>
        </Panel>

        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Checks" description="Run as you type. Nothing is sent to BRAIN.">
            {report.isError ? (
              <ErrorNotice error={report.error} title="Could not run the checks" />
            ) : (
              <Checks
                report={touched(form) ? report.data : undefined}
                pending={report.isFetching}
              />
            )}
          </Panel>

          <Panel
            title="Submit on BRAIN"
            description="BRAIN's form takes these seven values in this order."
            actions={
              <Button
                size="sm"
                variant="primary"
                disabled={!ready}
                render={<a href={BRAIN_URL} target="_blank" rel="noopener noreferrer" />}
              >
                <ExternalLinkIcon aria-hidden />
                Open BRAIN
              </Button>
            }
          >
            <div className="flex flex-col gap-3">
              {!ready && (
                <Notice tone="warn">
                  Fix what the checks flag first. The values can still be copied, but BRAIN will
                  reject or silently ignore what they describe.
                </Notice>
              )}
              <ul>
                <CopyRow label="Prompt name" value={form.name.trim()} />
                <CopyRow label="Prompt text" value={form.prompt} wide />
                <CopyRow label="Model" value={form.model} />
                <CopyRow label="Model version" value={form.model_version.trim()} />
                <CopyRow label="Update frequency" value={form.frequency} />
                <CopyRow
                  label="Weight"
                  value={Number.isFinite(form.weight) ? form.weight.toFixed(2) : ''}
                />
                <CopyRow label="Sample output" value={form.sample_output.trim()} wide />
              </ul>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-body-compact text-ink-subtle">
                  Once BRAIN has accepted it, record it here to keep your limits and coverage.
                </p>
                <Button size="sm" disabled={!ready} onClick={() => setConfirming(true)}>
                  I submitted it
                </Button>
              </div>
            </div>
          </Panel>
        </div>
      </div>

      <Panel
        title="Saved prompts"
        description="Your own record. BRAIN is the source of truth for what is running."
        bodyClassName="p-0"
      >
        {limits && (
          <div className="grid grid-cols-2 gap-3 border-b border-hairline p-4 lg:grid-cols-4">
            <Metric
              boxed
              label="Active"
              value={`${limits.active} / ${limits.maxActive}`}
              tone={limits.active > limits.maxActive ? 'loss' : 'neutral'}
              hint="Submitted with weight above 0"
            />
            <Metric
              boxed
              label="Submitted today"
              value={`${limits.today} / ${limits.maxPerDay}`}
              tone={limits.today > limits.maxPerDay ? 'loss' : 'neutral'}
            />
            <Metric
              boxed
              label="Instruments covered"
              value={fmt.int(limits.coverage)}
              hint={`BRAIN asks for ${fmt.int(limits.coverageTarget)} across all prompts`}
            />
          </div>
        )}
        {saved.isError ? (
          <div className="p-4">
            <ErrorNotice error={saved.error} title="Could not read saved prompts" />
          </div>
        ) : !meta ? (
          <Skeleton className="h-24" />
        ) : meta.drafts.length === 0 ? (
          <Empty title="No saved prompts yet">Save one to keep it and track what you submit.</Empty>
        ) : (
          <ul>
            {meta.drafts.map((d) => (
              <li
                key={d.id}
                className={cn(
                  'flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline px-4 py-2.5 last:border-0',
                  d.id === draftId && 'bg-surface-2',
                )}
              >
                <span className="min-w-0 flex-1 truncate text-body text-ink">
                  {d.name || 'Untitled'}
                </span>
                <Badge tone={d.status === 'submitted' ? 'profit' : 'muted'}>{d.status}</Badge>
                <span className="num text-body-compact text-ink-subtle">
                  {d.names} names · weight {d.weight.toFixed(2)} · {d.frequency}
                </span>
                <span className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => load(d)}>
                    Open
                  </Button>
                  {d.status === 'submitted' && (
                    <Button size="sm" variant="ghost" onClick={() => unmark.mutate(d)}>
                      Not submitted
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setDeleting(d)}>
                    Delete
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <p className="px-1 text-body-compact text-ink-subtle">
        To stop a prompt running, set its weight to 0 on BRAIN; there is no remove button there.{' '}
        <a href={BRAIN_URL} target="_blank" rel="noopener noreferrer" className={LINK}>
          Open BRAIN
        </a>
      </p>

      <Confirm
        open={confirming}
        onOpenChange={setConfirming}
        title="Record this prompt as submitted?"
        confirmLabel="Yes, I submitted it"
        pending={mark.isPending}
        onConfirm={() => mark.mutate()}
      >
        This only updates your own record here. Do it after BRAIN has accepted the prompt.
        {mark.isError && <ErrorNotice className="mt-3" error={mark.error} />}
      </Confirm>
      <Confirm
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name || 'this prompt'}?`}
        confirmLabel="Delete"
        danger
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      >
        This removes only your local copy. A prompt already submitted on BRAIN keeps running until
        its weight is set to 0 there.
        {remove.isError && <p className="mt-2">{errorMessage(remove.error)}</p>}
      </Confirm>
    </Page>
  )
}
