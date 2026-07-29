# Repo Manager

Een kleine lokale Windows-app om je GitHub-repositories te bekijken, vergelijken, klonen, updaten en starten.

## Kern

- Toont repositories uit je GitHub-account
- Vergelijkt GitHub met lokale mappen in `C:\Users\Hesse\Desktop\Codex`
- Statussen: `LIVE`, `LOCAL`, `OUTDATED`, `NIET LOKAAL`
- Favorieten met `+` en `×`
- Toont standaard alleen je eerste drie favorieten
- Vindt `.bat`-bestanden in iedere projectmap
- Kan repositories klonen en veilig updaten met `git pull --ff-only`

## Installeren

1. Installeer Python en Git.
2. Dubbelklik op `install.bat`.
3. Dubbelklik daarna op `start.bat`.
4. Maak in GitHub een fine-grained personal access token met alleen leestoegang tot je repositories.
5. Plak het token in Repo Manager.

## Statussen

| Status | Betekenis |
|---|---|
| LIVE | Lokale branch is 1:1 met GitHub |
| OUTDATED | De lokale branch loopt achter |
| LOCAL | Lokale wijzigingen, lokale commits of geen geldige Git-repo |
| NIET LOKAAL | Repository staat wel op GitHub, maar nog niet in de Codex-map |

## Veilig gedrag

Repo Manager gebruikt geen force pull, reset of automatische push. Lokale wijzigingen worden nooit overschreven. Updaten gebeurt alleen met `git pull --ff-only`.

## Configuratie

De configuratie wordt opgeslagen in:

```text
%APPDATA%\RepoManager\config.json
```

Hierin staan alleen de lokale hoofdmap en favorieten. Het GitHub-token wordt veilig bewaard in Windows Credential Manager.
