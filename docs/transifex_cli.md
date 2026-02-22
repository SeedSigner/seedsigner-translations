# SeedSigner Translations

## Transifex CLI
You can pull the latest translations directly from Transifex for all translated languages.

You'll need to create a Transifex user if you don't already have one. Your user will also
need some minimal role permissions within the SeedSigner Transifex project in order for
your user's API key to have access to the translations data.

* Install the [Transifex CLI](https://developers.transifex.com/docs/cli).
* [Create an API key](https://help.transifex.com/en/articles/6248858-generating-an-api-token)
for your Transifex user.
* From the `seedsigner/src/seedsigner/resources/seedsigner-translations` dir run:

    ```bash
    # --force, -f Force the download of the translations files regardless of whether timestamps on the local computer are newer than those on the server (default: false)
    # --all, -a   Whether to download all files (default: false)
    tx pull -f --all
    ```
    * We use `-f` because as we manipulate the .po files through our PR process, they may
      end up with newer timestamps even though the translation content has not changed.
      That timestamp would then mislead the `tx pull` to disregard newer translations.

* Then from the SeedSigner project root, compile the catalogs to process the *.po files into
*.mo:

    ```bash
    python setup.py compile_catalog
    ```

### Pulling translations for a specific language
Use the `--language, -l` flag with the `--force, -f` flag:
```bash
# Example: Spanish ("es")
tx pull -f -l es

# Or comma-separated list
tx pull -f -l pl,no
```


### Misc notes
The `.tx/config` is set to `minimum-perc = 15` (this means that the CLI will skip any
language whose translation completion falls below this minimum percentage).

You can manually override this by adding, for example, `--minimum-perc 25` to require at
least 25% translation completion.
