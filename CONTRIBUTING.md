# Contributing to Switch Bay

Thanks for your interest. A few things to know before you open a pull request.

## License of your contribution (inbound = outbound)

Switch Bay is licensed under the **Functional Source License 1.1 (ALv2 future
license)** — see [`LICENSE`](LICENSE). By submitting a contribution (a pull
request, patch, or any change) you agree that **your contribution is licensed to
the project and its users under the same terms as the project** — the FSL-1.1,
converting to Apache-2.0 on the same schedule. You keep the copyright to your
work; you are simply licensing it inbound on the same terms it goes out.

The FSL carries an explicit **patent license** and a defensive-termination
clause (see the *Patents* section of `LICENSE`), so your contribution's patent
rights flow to users, and a contributor who later sues over the software loses
their own patent license.

## Sign your commits (DCO)

We use the **Developer Certificate of Origin** ([DCO 1.1](https://developercertificate.org/)).
It is a lightweight, per-commit attestation that you have the right to submit
your work under the project's license. There is nothing to sign and store — you
just add a trailer line to each commit:

```
Signed-off-by: Your Name <you@example.com>
```

The easy way is to pass `-s` when you commit:

```
git commit -s -m "your message"
```

If you forgot on an existing branch, add the sign-off retroactively:

```
git rebase --signoff origin/main
```

A CI check (see [`.github/workflows/dco.yml`](.github/workflows/dco.yml))
verifies every commit in a PR carries a matching `Signed-off-by`. Nothing is
stored beyond the line in your commit — the git history *is* the record.

The DCO text you certify by signing off:

> By making a contribution to this project, I certify that:
>
> (a) The contribution was created in whole or in part by me and I have the right
> to submit it under the open source license indicated in the file; or
>
> (b) The contribution is based upon previous work that, to the best of my
> knowledge, is covered under an appropriate open source license and I have the
> right under that license to submit that work with modifications, whether
> created in whole or in part by me, under the same open source license (unless I
> am permitted to submit under a different license), as indicated in the file; or
>
> (c) The contribution was provided directly to me by some other person who
> certified (a), (b) or (c) and I have not modified it.
>
> (d) I understand and agree that this project and the contribution are public
> and that a record of the contribution (including all personal information I
> submit with it, including my sign-off) is maintained indefinitely and may be
> redistributed consistent with this project or the open source license(s)
> involved.

## Notes

- If a contribution is made on behalf of a company, please make sure you have
  your employer's authorization to submit it under these terms.
- Maintainers may accept, request changes to, or decline any contribution at
  their discretion.

## Dependency install-script policy

`frontend/package.json` runs pnpm in allowlist mode: only the packages in
`pnpm.onlyBuiltDependencies` may run install scripts (`esbuild` and
`@tailwindcss/oxide` — both fetch a platform binary and genuinely need one).
Everything else is blocked, which is the default we want.

pnpm warns on each install about blocked scripts it hasn't been told about, so
deliberate refusals go in `pnpm.ignoredBuiltDependencies` to keep `make install`
output clean:

- **`protobufjs`** (transitive: `@grpc/grpc-js` → `@grpc/proto-loader`) — its
  `postinstall` only prints a version-scheme advisory to stderr. It writes no
  files and builds nothing, so skipping it is a no-op.

When a new dependency trips this warning, read its install script before
choosing a list: `onlyBuiltDependencies` if the package is genuinely unusable
without it, `ignoredBuiltDependencies` (with a line here saying why) otherwise.
