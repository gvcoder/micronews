"""
News_Agent: CrewAI-based agent for searching and summarizing news by category.
"""
import logging
from crewai import Agent, Task, Crew
from langchain_community.tools import DuckDuckGoSearchRun

logger = logging.getLogger(__name__)


def build_news_crew(category_name: str) -> Crew:
    """Build and return a Crew configured to collect news for the given category."""
    search_tool = DuckDuckGoSearchRun()

    news_agent = Agent(
        role='News Researcher',
        goal='Find and summarize recent news articles for a given category',
        backstory='Expert news analyst who writes concise, accurate summaries.',
        tools=[search_tool],
        verbose=False,
    )

    search_task = Task(
        description=(
            f'Search for the top 10 most recent news articles about "{category_name}". '
            'For each article found, provide the headline, a brief summary, and the source URL if available. '
            'Format each article as:\n'
            'HEADLINE: <title>\n'
            'SUMMARY: <summary text>\n'
            'URL: <url or "N/A">\n'
            '---'
        ),
        agent=news_agent,
        expected_output=(
            'A list of up to 10 news articles, each with HEADLINE, SUMMARY, and URL fields separated by ---'
        ),
    )

    summarize_task = Task(
        description=(
            f'Review the articles found about "{category_name}" and ensure each summary is '
            '60 words or fewer. If any summary exceeds 60 words, rewrite it to be concise. '
            'Keep the same HEADLINE/SUMMARY/URL format with --- separators.'
        ),
        agent=news_agent,
        expected_output=(
            'A refined list of up to 10 news articles with summaries of 60 words or fewer, '
            'in HEADLINE/SUMMARY/URL format separated by ---'
        ),
    )

    crew = Crew(
        agents=[news_agent],
        tasks=[search_task, summarize_task],
        verbose=False,
    )

    return crew
