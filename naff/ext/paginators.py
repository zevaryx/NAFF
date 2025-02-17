import asyncio
import textwrap
import uuid
from typing import List, TYPE_CHECKING, Optional, Callable, Coroutine, Union

from naff import (
    Embed,
    ComponentContext,
    ActionRow,
    Button,
    ButtonStyles,
    spread_to_rows,
    ComponentCommand,
    Context,
    PrefixedContext,
    Message,
    MISSING,
    Snowflake_Type,
    Select,
    SelectOption,
    Color,
    BrandColors,
)
from naff.client.utils.attr_utils import define, field
from naff.client.utils.serializer import export_converter
from naff.models.discord.emoji import process_emoji

if TYPE_CHECKING:
    from naff import Client
    from naff.models.discord.emoji import PartialEmoji

__all__ = ("Paginator",)


@define(kw_only=False)
class Timeout:
    paginator: "Paginator" = field()
    """The paginator that this timeout is associated with."""
    run: bool = field(default=True)
    """Whether or not this timeout is currently running."""
    ping: asyncio.Event = asyncio.Event()
    """The event that is used to wait the paginator action."""

    async def __call__(self) -> None:
        while self.run:
            try:
                await asyncio.wait_for(self.ping.wait(), timeout=self.paginator.timeout_interval)
            except asyncio.TimeoutError:
                if self.paginator.message:
                    await self.paginator.message.edit(components=self.paginator.create_components(True))
                return
            else:
                self.ping.clear()


@define(kw_only=False)
class Page:
    content: str = field()
    """The content of the page."""
    title: Optional[str] = field(default=None)
    """The title of the page."""
    prefix: str = field(kw_only=True, default="")
    """Content that is prepended to the page."""
    suffix: str = field(kw_only=True, default="")
    """Content that is appended to the page."""

    @property
    def get_summary(self) -> str:
        """Get the short version of the page content."""
        return self.title or textwrap.shorten(self.content, 40, placeholder="...")

    def to_embed(self) -> Embed:
        """Process the page to an embed."""
        return Embed(description=f"{self.prefix}\n{self.content}\n{self.suffix}", title=self.title)


@define(kw_only=False)
class Paginator:
    client: "Client" = field()
    """The NAFF client to hook listeners into"""

    page_index: int = field(kw_only=True, default=0)
    """The index of the current page being displayed"""
    pages: List[Page | Embed] = field(factory=list, kw_only=True)
    """The pages this paginator holds"""
    timeout_interval: int = field(default=0, kw_only=True)
    """How long until this paginator disables itself"""
    callback: Callable[..., Coroutine] = field(default=None)
    """A coroutine to call should the select button be pressed"""

    show_first_button: bool = field(default=True)
    """Should a `First` button be shown"""
    show_back_button: bool = field(default=True)
    """Should a `Back` button be shown"""
    show_next_button: bool = field(default=True)
    """Should a `Next` button be shown"""
    show_last_button: bool = field(default=True)
    """Should a `Last` button be shown"""
    show_callback_button: bool = field(default=False)
    """Show a button which will call the `callback`"""
    show_select_menu: bool = field(default=False)
    """Should a select menu be shown for navigation"""

    first_button_emoji: Optional[Union["PartialEmoji", dict, str]] = field(
        default="⏮️", metadata=export_converter(process_emoji)
    )
    """The emoji to use for the first button"""
    back_button_emoji: Optional[Union["PartialEmoji", dict, str]] = field(
        default="⬅️", metadata=export_converter(process_emoji)
    )
    """The emoji to use for the back button"""
    next_button_emoji: Optional[Union["PartialEmoji", dict, str]] = field(
        default="➡️", metadata=export_converter(process_emoji)
    )
    """The emoji to use for the next button"""
    last_button_emoji: Optional[Union["PartialEmoji", dict, str]] = field(
        default="⏩", metadata=export_converter(process_emoji)
    )
    """The emoji to use for the last button"""
    callback_button_emoji: Optional[Union["PartialEmoji", dict, str]] = field(
        default="✅", metadata=export_converter(process_emoji)
    )
    """The emoji to use for the callback button"""

    wrong_user_message: str = field(default="This paginator is not for you")
    """The message to be sent when the wrong user uses this paginator"""

    default_title: Optional[str] = field(default=None)
    """The default title to show on the embeds"""
    default_color: Color = field(default=BrandColors.BLURPLE)
    """The default colour to show on the embeds"""
    default_button_color: Union[ButtonStyles, int] = field(default=ButtonStyles.BLURPLE)
    """The color of the buttons"""

    _uuid: str = field(factory=uuid.uuid4)
    _message: Message = field(default=MISSING)
    _timeout_task: Timeout = field(default=MISSING)
    _author_id: Snowflake_Type = field(default=MISSING)

    def __attrs_post_init__(self) -> None:
        self.client.add_component_callback(
            ComponentCommand(
                name=f"Paginator:{self._uuid}",
                callback=self._on_button,
                listeners=[
                    f"{self._uuid}|select",
                    f"{self._uuid}|first",
                    f"{self._uuid}|back",
                    f"{self._uuid}|callback",
                    f"{self._uuid}|next",
                    f"{self._uuid}|last",
                ],
            )
        )

    @property
    def message(self) -> Message:
        """The message this paginator is currently attached to"""
        return self._message

    @property
    def author_id(self) -> Snowflake_Type:
        """The ID of the author of the message this paginator is currently attached to"""
        return self._author_id

    @classmethod
    def create_from_embeds(cls, client: "Client", *embeds: Embed, timeout: int = 0) -> "Paginator":
        """Create a paginator system from a list of embeds.

        Args:
            client: A reference to the NAFF client
            embeds: The embeds to use for each page
            timeout: A timeout to wait before closing the paginator

        Returns:
            A paginator system
        """
        return cls(client, pages=list(embeds), timeout_interval=timeout)

    @classmethod
    def create_from_string(
        cls, client: "Client", content: str, prefix: str = "", suffix: str = "", page_size: int = 4000, timeout: int = 0
    ) -> "Paginator":
        """
        Create a paginator system from a string.

        Args:
            client: A reference to the NAFF client
            content: The content to paginate
            prefix: The prefix for each page to use
            suffix: The suffix for each page to use
            page_size: The maximum characters for each page
            timeout: A timeout to wait before closing the paginator

        Returns:
            A paginator system
        """
        content_pages = textwrap.wrap(
            content,
            width=page_size - (len(prefix) + len(suffix)),
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        )
        pages = [Page(c, prefix=prefix, suffix=suffix) for c in content_pages]
        return cls(client, pages=pages, timeout_interval=timeout)

    @classmethod
    def create_from_list(
        cls,
        client: "Client",
        content: list[str],
        prefix: str = "",
        suffix: str = "",
        page_size: int = 4000,
        timeout: int = 0,
    ) -> "Paginator":
        """
        Create a paginator from a list of strings. Useful to maintain formatting.

        Args:
            client: A reference to the NAFF client
            content: The content to paginate
            prefix: The prefix for each page to use
            suffix: The suffix for each page to use
            page_size: The maximum characters for each page
            timeout: A timeout to wait before closing the paginator

        Returns:
            A paginator system
        """
        pages = []
        page = ""
        for entry in content:
            if len(page) + len(f"\n{entry}") <= page_size:
                page += f"{entry}\n"
            else:
                pages.append(Page(page, prefix=prefix, suffix=suffix))
                page = ""
        if page != "":
            pages.append(Page(page, prefix=prefix, suffix=suffix))
        return cls(client, pages=pages, timeout_interval=timeout)

    def create_components(self, disable: bool = False) -> List[ActionRow]:
        """
        Create the components for the paginator message.

        Args:
            disable: Should all the components be disabled?

        Returns:
            A list of ActionRows

        """
        output = []

        if self.show_select_menu:
            current = self.pages[self.page_index]
            output.append(
                Select(
                    [
                        SelectOption(f"{i+1} {p.get_summary if isinstance(p, Page) else p.title}", str(i))
                        for i, p in enumerate(self.pages)
                    ],
                    custom_id=f"{self._uuid}|select",
                    placeholder=f"{self.page_index+1} {current.get_summary if isinstance(current, Page) else current.title}",
                    max_values=1,
                    disabled=disable,
                )
            )

        if self.show_first_button:
            output.append(
                Button(
                    self.default_button_color,
                    emoji=self.first_button_emoji,
                    custom_id=f"{self._uuid}|first",
                    disabled=disable or self.page_index == 0,
                )
            )
        if self.show_back_button:
            output.append(
                Button(
                    self.default_button_color,
                    emoji=self.back_button_emoji,
                    custom_id=f"{self._uuid}|back",
                    disabled=disable or self.page_index == 0,
                )
            )

        if self.show_callback_button:
            output.append(
                Button(
                    self.default_button_color,
                    emoji=self.callback_button_emoji,
                    custom_id=f"{self._uuid}|callback",
                    disabled=disable,
                )
            )

        if self.show_next_button:
            output.append(
                Button(
                    self.default_button_color,
                    emoji=self.next_button_emoji,
                    custom_id=f"{self._uuid}|next",
                    disabled=disable or self.page_index >= len(self.pages) - 1,
                )
            )
        if self.show_last_button:
            output.append(
                Button(
                    self.default_button_color,
                    emoji=self.last_button_emoji,
                    custom_id=f"{self._uuid}|last",
                    disabled=disable or self.page_index >= len(self.pages) - 1,
                )
            )

        return spread_to_rows(*output)

    def to_dict(self) -> dict:
        """Convert this paginator into a dictionary for sending."""
        page = self.pages[self.page_index]

        if isinstance(page, Page):
            page = page.to_embed()
            if not page.title and self.default_title:
                page.title = self.default_title
        if not page.footer:
            page.set_footer(f"Page {self.page_index+1}/{len(self.pages)}")
        if not page.color:
            page.color = self.default_color

        return {"embeds": [page.to_dict()], "components": [c.to_dict() for c in self.create_components()]}

    async def send(self, ctx: Context) -> Message:
        """
        Send this paginator.

        Args:
            ctx: The context to send this paginator with

        Returns:
            The resulting message

        """
        self._message = await ctx.send(**self.to_dict())
        self._author_id = ctx.author.id

        if self.timeout_interval > 1:
            self._timeout_task = Timeout(self)
            asyncio.create_task(self._timeout_task())

        return self._message

    async def reply(self, ctx: PrefixedContext) -> Message:
        """
        Reply this paginator to ctx.

        Args:
            ctx: The context to reply this paginator with
        Returns:
            The resulting message
        """
        self._message = await ctx.reply(**self.to_dict())
        self._author_id = ctx.author.id

        if self.timeout_interval > 1:
            self._timeout_task = Timeout(self)
            asyncio.create_task(self._timeout_task())

        return self._message

    async def stop(self) -> None:
        """Disable this paginator."""
        if self._timeout_task:
            self._timeout_task.run = False
            self._timeout_task.ping.set()
        await self._message.edit(components=self.create_components(True))

    async def update(self) -> None:
        """
        Update the paginator to the current state.

        Use this if you have programmatically changed the page_index

        """
        await self._message.edit(**self.to_dict())

    async def _on_button(self, ctx: ComponentContext, *args, **kwargs) -> Optional[Message]:
        if ctx.author.id == self.author_id:
            if self._timeout_task:
                self._timeout_task.ping.set()
            match ctx.custom_id.split("|")[1]:
                case "first":
                    self.page_index = 0
                case "last":
                    self.page_index = len(self.pages) - 1
                case "next":
                    if (self.page_index + 1) < len(self.pages):
                        self.page_index += 1
                case "back":
                    if (self.page_index - 1) >= 0:
                        self.page_index -= 1
                case "select":
                    self.page_index = int(ctx.values[0])
                case "callback":
                    if self.callback:
                        return await self.callback(ctx)

            await ctx.edit_origin(**self.to_dict())
        else:
            if self.wrong_user_message:
                return await ctx.send(self.wrong_user_message, ephemeral=True)
            else:
                # silently ignore
                return await ctx.defer(edit_origin=True)
