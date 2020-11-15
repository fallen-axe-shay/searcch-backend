# logic for /artifacts

from api.app import db
from models.model import *
from models.schema import *
from flask import abort, jsonify, request, make_response, Blueprint, url_for
from flask_restful import reqparse, Resource, fields, marshal
from sqlalchemy import func, desc


class ArtifactListAPI(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        """
        possible filters:
            - keywords
            - author
            - type
            - organization
        """
        self.reqparse.add_argument(name='keywords',
                                   type=str,
                                   required=True,
                                   help='missing keywords in query string')
        # TODO: add all filters for filtered search here

        super(ArtifactListAPI, self).__init__()

    @staticmethod
    def generate_artifact_uri(artifact_id):
        return url_for('api.artifact', artifact_id=artifact_id)

    def get(self):
        args = self.reqparse.parse_args()
        keywords = args['keywords']

        if keywords == '':
            docs = db.session.query(Artifact).limit(20).all()
        else:
            sqratings = db.session.query(ArtifactRatings.artifact_id, func.count(ArtifactRatings.id).label(
                'num_ratings'), func.avg(ArtifactRatings.rating).label('avg_rating')).group_by("artifact_id").subquery()
            sqreviews = db.session.query(ArtifactReviews.artifact_id, func.count(
                ArtifactReviews.id).label('num_reviews')).group_by("artifact_id").subquery()
            res = db.session.query(Artifact, func.ts_rank_cd(Artifact.document_with_idx, func.plainto_tsquery("english", keywords)).label("rank"), 'num_ratings', 'avg_rating', 'num_reviews').filter(
                Artifact.document_with_idx.match(keywords, postgresql_regconfig='english')).join(sqratings, Artifact.id == sqratings.c.artifact_id, isouter=True).join(sqreviews, Artifact.id == sqreviews.c.artifact_id, isouter=True).order_by(desc("rank")).all()

        artifacts = []
        for artifact, relevance_score, num_ratings, avg_rating, num_reviews in res:
            result = {
                "id": artifact.id,
                "uri": ArtifactListAPI.generate_artifact_uri(artifact.id),
                "doi": artifact.url,
                "type": artifact.type,
                "relevance_score": relevance_score,
                "title": artifact.title,
                "description": artifact.description,
                "avg_rating": float(avg_rating) if avg_rating else None,
                "num_ratings": num_ratings if num_ratings else 0,
                "num_reviews": num_reviews if num_reviews else 0
            }
            artifacts.append(result)

        response = jsonify({"artifacts": artifacts, "length": len(artifacts)})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.status_code = 200
        return response


class ArtifactAPI(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument(name='userid',
                                   type=int,
                                   required=True,
                                   help='missing user id in query string')

        super(ArtifactAPI, self).__init__()

    def get(self, artifact_id):
        args = self.reqparse.parse_args()
        user_id = args['userid']

        artifact = db.session.query(Artifact).filter(
            Artifact.id == artifact_id).first()
        if not artifact:
            abort(404, description='invalid ID for artifact')

        # get average rating for the artifact, number of ratings
        sqratings = db.session.query(ArtifactRatings.artifact_id, func.count(ArtifactRatings.id).label('num_ratings'), func.avg(ArtifactRatings.rating).label('avg_rating')).filter(ArtifactRatings.artifact_id == artifact_id).group_by("artifact_id").all()        
        sqreviews = db.session.query(ArtifactReviews).filter(ArtifactReviews.artifact_id == artifact_id).all()

        # get whether the user has favorited that artifact
        sqfavorites = db.session.query(ArtifactFavorites.artifact_id).filter(ArtifactFavorites.artifact_id == artifact_id, ArtifactFavorites.user_id == user_id).all()
        
        artifact_affiliations = db.session.query(ArtifactAffiliation.affiliation_id).filter(
            ArtifactAffiliation.artifact_id == artifact_id).subquery()
        affiliations = db.session.query(Affiliation).filter(
            Affiliation.id.in_(artifact_affiliations)).all()

        artifact_schema = ArtifactSchema()
        affiliation_schema = AffiliationSchema(many=True)
        # TODO: get username for each review user
        review_schema = ArtifactReviewsSchema(many=True)

        response = jsonify({
            "artifact": artifact_schema.dump(artifact),
            "affiliations": affiliation_schema.dump(affiliations),
            "num_ratings": sqratings[0][1],
            "avg_rating": float(sqratings[0][2]),
            "num_reviews": len(sqreviews),
            "reviews": review_schema.dump(sqreviews),
            "is_favorited": True if sqfavorites else False
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.status_code = 200
        return response
