"""
MT4/MT5 License Creation Bot for Discord
=========================================
Triggers via button click → collects info via Modal → confirmation → creates license via mt5.app API
Secrets are loaded from environment variables (safe for cloud hosting).
"""

import discord
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput, Select
import aiohttp
import os
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIG — loaded from environment variables
#  Set these in Railway dashboard, never hardcode them!
# ─────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
MT5APP_API_KEY    = os.environ["MT5APP_API_KEY"]
EA_ID_MT4         = os.environ["EA_ID_MT4"]
EA_ID_MT5         = os.environ["EA_ID_MT5"]
MT5APP_API_BASE   = "https://mt5.app/api/v1/licenses"

# Expiry days per plan
EXPIRY_DAYS = {
    "monthly":  30,
    "lifetime": 36500,   # 100 years ≈ lifetime
}
# ─────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ══════════════════════════════════════════════
#  STEP 1 — Modal: collect customer details
# ══════════════════════════════════════════════
class LicenseInfoModal(Modal, title="🔑 New License — Customer Details"):
    real_name = TextInput(
        label="Customer Full Name",
        placeholder="e.g. João Silva",
        required=True,
        max_length=100,
    )
    email = TextInput(
        label="Customer Email",
        placeholder="e.g. joao@example.com",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        view = PlanPlatformView(
            real_name=self.real_name.value.strip(),
            email=self.email.value.strip(),
        )
        embed = discord.Embed(
            title="Step 2 of 3 — Plan & Platform",
            description=(
                f"**Customer:** {self.real_name.value.strip()}\n"
                f"**Email:** {self.email.value.strip()}\n\n"
                "Please choose the **plan type** and **platform(s)**:"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ══════════════════════════════════════════════
#  STEP 2 — Select plan type + platforms
# ══════════════════════════════════════════════
class PlanSelect(Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(label="Monthly (30 days)", value="monthly",  emoji="📅"),
            discord.SelectOption(label="Lifetime",          value="lifetime", emoji="♾️"),
        ]
        super().__init__(placeholder="Choose plan type…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.plan = self.values[0]
        await interaction.response.defer()


class PlatformSelect(Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(label="MT4 only",       value="mt4",     emoji="4️⃣"),
            discord.SelectOption(label="MT5 only",       value="mt5",     emoji="5️⃣"),
            discord.SelectOption(label="MT4 + MT5 both", value="mt4+mt5", emoji="✅"),
        ]
        super().__init__(placeholder="Choose platform(s)…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.platforms = self.values[0]
        await interaction.response.defer()


class PlanPlatformView(View):
    def __init__(self, real_name: str, email: str):
        super().__init__(timeout=300)
        self.real_name = real_name
        self.email = email
        self.plan: str | None = None
        self.platforms: str | None = None
        self.add_item(PlanSelect(self))
        self.add_item(PlatformSelect(self))

    @discord.ui.button(label="Next → Review", style=discord.ButtonStyle.green, row=2)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if not self.plan or not self.platforms:
            await interaction.response.send_message(
                "⚠️ Please select both a **plan** and a **platform** before continuing.",
                ephemeral=True,
            )
            return
        view = ConfirmView(
            real_name=self.real_name,
            email=self.email,
            plan=self.plan,
            platforms=self.platforms,
            requested_by=interaction.user,
        )
        platform_label = {"mt4": "MT4", "mt5": "MT5", "mt4+mt5": "MT4 + MT5"}[self.platforms]
        plan_label     = {"monthly": "Monthly (30 days)", "lifetime": "Lifetime"}[self.plan]
        embed = discord.Embed(
            title="Step 3 of 3 — Confirm License Creation",
            color=discord.Color.orange(),
        )
        embed.add_field(name="👤 Customer Name", value=self.real_name,  inline=True)
        embed.add_field(name="📧 Email",         value=self.email,       inline=True)
        embed.add_field(name="📅 Plan",          value=plan_label,       inline=True)
        embed.add_field(name="🖥️ Platform",      value=platform_label,   inline=True)
        embed.add_field(name="⏳ Expiry",        value=f"{EXPIRY_DAYS[self.plan]} days", inline=True)
        embed.set_footer(text="Click ✅ Confirm to create the license(s) or ❌ Cancel to abort.")
        await interaction.response.edit_message(embed=embed, view=view)


# ══════════════════════════════════════════════
#  STEP 3 — Confirmation
# ══════════════════════════════════════════════
class ConfirmView(View):
    def __init__(self, real_name, email, plan, platforms, requested_by):
        super().__init__(timeout=180)
        self.real_name    = real_name
        self.email        = email
        self.plan         = plan
        self.platforms    = platforms
        self.requested_by = requested_by

    @discord.ui.button(label="✅ Confirm — Create License", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content="⏳ Creating license(s), please wait…",
            embed=None,
            view=None,
        )
        results = await create_licenses(
            real_name=self.real_name,
            email=self.email,
            plan=self.plan,
            platforms=self.platforms,
        )
        embed = build_result_embed(
            results, self.real_name, self.email,
            self.plan, self.platforms, self.requested_by
        )
        await interaction.edit_original_response(content=None, embed=embed)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content="❌ License creation cancelled.",
            embed=None,
            view=None,
        )


# ══════════════════════════════════════════════
#  API — create license(s) on mt5.app
# ══════════════════════════════════════════════
async def create_one_license(session: aiohttp.ClientSession, ea_id: str, plan: str, email: str, real_name: str) -> dict:
    # Minimal payload — only send what's needed, let mt5.app use defaults for everything else
    payload = {
        "eaId":           ea_id,
        "customerEmail":  email,
        "customerName":   real_name,
        "maxActivations": 10,
        "autoRenew":      True,
        "type":           "LIVE",
    }

    if plan == "lifetime":
        payload["lifetime"]  = True
        payload["expiresAt"] = None
    else:
        payload["expiresAt"]     = None
        payload["durationValue"] = 1
        payload["durationUnit"]  = "month"

    print(f"[API] Sending payload: {payload}")

    headers = {
        "Authorization": f"Bearer {MT5APP_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with session.post(
            MT5APP_API_BASE,              # POST /api/v1/licenses
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            import json as _json
            raw = await resp.text()
            print(f"[API] Status: {resp.status}")
            print(f"[API] Raw response: {raw[:500]}")
            try:
                data = _json.loads(raw)
            except Exception:
                return {"ok": False, "error": f"Non-JSON response (HTTP {resp.status}): {raw[:200]}"}

            if resp.status in (200, 201):
                return {"ok": True, "license": data}
            else:
                return {"ok": False, "error": data.get("message", data.get("error", f"HTTP {resp.status}"))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def create_licenses(real_name, email, plan, platforms) -> dict:
    results = {}
    async with aiohttp.ClientSession() as session:
        tasks = {}
        if platforms in ("mt4", "mt4+mt5"):
            tasks["MT4"] = create_one_license(session, EA_ID_MT4, plan, email, real_name)
        if platforms in ("mt5", "mt4+mt5"):
            tasks["MT5"] = create_one_license(session, EA_ID_MT5, plan, email, real_name)
        for platform, coro in tasks.items():
            results[platform] = await coro
    return results


def build_result_embed(results, real_name, email, plan, platforms, requested_by) -> discord.Embed:
    all_ok = all(r["ok"] for r in results.values())
    color  = discord.Color.green() if all_ok else discord.Color.red()
    title  = "✅ License(s) Created Successfully" if all_ok else "⚠️ License Creation — Partial / Failed"

    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="👤 Customer", value=real_name,          inline=True)
    embed.add_field(name="📧 Email",    value=email,               inline=True)
    embed.add_field(name="📅 Plan",     value=plan.capitalize(),   inline=True)

    for platform, result in results.items():
        if result["ok"]:
            lic = result["license"]
            # mt5.app returns the license object directly
            key = lic.get("key") or lic.get("licenseKey") or lic.get("id", "N/A")
            embed.add_field(
                name=f"🔑 {platform} License Key",
                value=f"```{key}```",
                inline=False,
            )
            embed.add_field(
                name=f"{platform} Details",
                value=(
                    f"ID: `{lic.get('id', 'N/A')}`\n"
                    f"Status: `{lic.get('status', 'N/A')}`\n"
                    f"Expires: `{lic.get('expiresAt') or lic.get('expires_at') or 'Lifetime'}`\n"
                    f"Activations: `{lic.get('activationsUsed', 0)}/{lic.get('maxActivations', 1)}`"
                ),
                inline=True,
            )
        else:
            embed.add_field(
                name=f"❌ {platform} — Failed",
                value=f"Error: {result['error']}",
                inline=False,
            )

    embed.set_footer(text=f"Requested by {requested_by.display_name} ({requested_by.id})")
    return embed


# ══════════════════════════════════════════════
#  TRIGGER BUTTON — persistent panel
# ══════════════════════════════════════════════
class TriggerView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔑 Create New License",
        style=discord.ButtonStyle.primary,
        custom_id="open_license_modal",
    )
    async def open_modal(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(LicenseInfoModal())


# ══════════════════════════════════════════════
#  SLASH COMMAND — post trigger panel
# ══════════════════════════════════════════════
@tree.command(name="setup_license_panel", description="Post the license creation button panel in this channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_license_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔑 MT4/MT5 License Manager",
        description=(
            "Click the button below to start the license creation workflow.\n\n"
            "You will be asked for:\n"
            "• Customer name & email\n"
            "• Plan type (Monthly / Lifetime)\n"
            "• Platform (MT4 / MT5 / Both)\n\n"
            "A confirmation step will appear before anything is created."
        ),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="EA License Manager • mt5.app")
    await interaction.channel.send(embed=embed, view=TriggerView())
    await interaction.response.send_message("✅ Panel posted!", ephemeral=True)


# ══════════════════════════════════════════════
#  BOT STARTUP
# ══════════════════════════════════════════════
@client.event
async def on_ready():
    client.add_view(TriggerView())
    await tree.sync()
    print(f"✅ Bot online as {client.user} | Commands synced")


client.run(DISCORD_BOT_TOKEN)
