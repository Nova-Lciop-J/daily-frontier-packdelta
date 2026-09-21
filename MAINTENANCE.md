# Maintenance

Run `python -m unittest discover -s tests -v`, rebuild the zipapp, and rerun the
README example after changes. Review current Python security advisories before
publication; zero package dependencies does not remove interpreter risk.

Supporting a new archive type, raising input limits, changing report schema or
exit-code semantics requires focused tests and a reviewed version change.
Real findings should drive changes. A maintenance inspection may legitimately
result in no code change. No independent public CI has run yet.
