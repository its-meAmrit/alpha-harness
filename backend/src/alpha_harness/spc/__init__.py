"""Systematic Prediction Challenge (SPC): check a prompt and its sample output before it is
submitted on BRAIN, and keep a local record of what was submitted.

BRAIN offers no public API for submitting an SPC prompt, so this package never talks to the
platform. It does everything that can be done beforehand — the structural checks BRAIN's own
validation applies, the mistakes the community guides warn about — and hands back the exact
values for the platform's form.
"""
