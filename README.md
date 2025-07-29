# Bot discord simple

Ce bot Discord est conçu pour gérer la modération, la gestion des rôles, l'automodération, le système de niveaux, et bien plus encore.

---

## Fonctionnalités principales

- Gestion des rôles (ajout, suppression, création)
- Commandes de modération (ban, kick, mute, unmute)
- Automodération (antispam, antilink, antibadword, antimassmention)
- Système de niveaux avec gains d'XP en message et vocal
- Configuration avancée des punitions
- Logs automatiques et configuration facile
- Commande help interactive avec navigation par boutons

---

## Crée le bot

============================================================
1. Créer une application Discord et un bot
============================================================

1. Va sur le site Discord Developer Portal : https://discord.com/developers/applications
2. Connecte-toi avec ton compte Discord.
3. Clique sur "New Application" (Nouvelle application).
4. Donne un nom à ton application puis clique sur "Create".
5. Dans le menu à gauche, clique sur "Bot".
6. Clique sur "Add Bot" puis "Yes, do it!" pour confirmer.
7. Ici, tu peux définir l’avatar, le nom de ton bot, et surtout copier le token du bot.
   ⚠️ Ce token est très important, il sert à authentifier ton bot.
   ⚠️ Garde-le secret ! Ne le partage jamais.

============================================================
2. Inviter ton bot sur un serveur Discord
============================================================

1. Dans le Developer Portal, va dans "OAuth2 > URL Generator".
2. Dans "Scopes", coche la case "bot".
3. Dans "Bot Permissions", sélectionne les permissions que ton bot aura 
   (exemples : envoyer des messages, gérer les messages, lire les messages, etc.).
4. En bas, un lien est généré automatiquement. Copie ce lien.
5. Ouvre ce lien dans ton navigateur.
6. Choisis le serveur où tu veux ajouter le bot (tu dois être admin du serveur).
7. Clique sur "Autoriser" pour inviter ton bot sur le serveur.

## Installation

1. Clonez ce dépôt ou téléchargez les fichiers.

2. Installez Python 3.10+ ([télécharger ici](https://www.python.org/downloads/)).

3. Installez les dépendances avec pip :

   ```bash
   pip install -r requirements.txt

4. Mettez le token de votre bot tout en bas bot.run('TON TOKEN')

5. inviter votre bot sur votre serveur | https://discord.com/oauth2/authorize?client_id=ID DE ON BOT&scope=bot&permissions=8

6. Faites clique droit sur le fichier bot.py --> ouvrir avec --> python

Si vous rencontrez différent problèmes sur votre bot veuillez me contacter via discord
pseudo : 452213119
